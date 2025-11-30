# wallix_ssh.py created by Mickael ASSELINE (PAPAMICA)
# https://github.com/PAPAMICA/wallix_ssh
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import subprocess
import argparse
import sys
from typing import List, Dict
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from rich.logging import RichHandler
import logging
import getpass
import base64
import gzip
import configparser

# Load configuration from config.ini
def load_config():
    """Load configuration from config.ini file"""
    config = configparser.ConfigParser()
    script_dir = Path(__file__).parent.absolute()
    config_file = script_dir / 'config.ini'
    
    if not config_file.exists():
        print(f"Error: Configuration file not found: {config_file}", file=sys.stderr)
        print("Please create a config.ini file in the script directory", file=sys.stderr)
        sys.exit(1)
    
    config.read(config_file)
    
    cache_file = config.get('wallix', 'cache_file', fallback='')
    if not cache_file:
        cache_file = str(Path.home() / '.wallix_cache')
    
    # Parse deploy files list (comma-separated)
    deploy_files_str = config.get('wallix', 'deploy_files', fallback='')
    deploy_files = [f.strip() for f in deploy_files_str.split(',') if f.strip()] if deploy_files_str else []
    
    return {
        'username': config.get('wallix', 'username', fallback=''),
        'password': config.get('wallix', 'password', fallback=''),
        'base_url': config.get('wallix', 'base_url', fallback=''),
        'cache_file': cache_file,
        'deploy_files': deploy_files
    }

# Load configuration
CONFIG = load_config()
WALLIX_USERNAME = CONFIG['username']
WALLIX_PASSWORD = CONFIG['password']
WALLIX_BASE_URL = CONFIG['base_url']
WALLIX_CACHE_FILE = CONFIG['cache_file']
WALLIX_DEPLOY_FILES = CONFIG['deploy_files']

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)
logger = logging.getLogger("wallix")

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class WallixManager:
    def __init__(self):
        self.base_url = WALLIX_BASE_URL
        self.username = WALLIX_USERNAME
        self.password = WALLIX_PASSWORD
        self.api_endpoint = f'{self.base_url}/api'
        self.devices_endpoint = f'{self.base_url}/api/devices'
        self.session = requests.Session()
        self.session.trust_env = False
        # Use configured cache file path or default
        self.cache_file = Path(WALLIX_CACHE_FILE).expanduser()
        self.history_file = Path.home() / '.wallix_history'
        self.cache_duration = timedelta(days=7)
        self.console = Console()
        # Extract hostname from base_url for SSH commands
        from urllib.parse import urlparse
        parsed_url = urlparse(self.base_url)
        self.bastion_host = parsed_url.netloc or parsed_url.path

    def load_cache(self, force_refresh: bool = False) -> List[Dict]:
        """Load devices from cache"""
        if force_refresh:
            logger.info("Forcing cache refresh...")
            return None

        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    cache_data = json.load(f)
                    cache_age = datetime.now() - datetime.fromisoformat(cache_data['timestamp'])

                    # Calculate different time units
                    total_minutes = int(cache_age.total_seconds() / 60)
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    days = hours // 24
                    hours = hours % 24

                    # Formatted display
                    age_str = ""
                    if days > 0:
                        age_str += f"{days} day{'s' if days > 1 else ''}, "
                    if hours > 0:
                        age_str += f"{hours} hour{'s' if hours > 1 else ''}, "
                    age_str += f"{minutes} minute{'s' if minutes > 1 else ''}"

                    logger.info(f"Cache found (age: {age_str})")
                    return cache_data['devices']
            else:
                logger.info("No cache found")
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
        return None

    def save_cache(self, devices: List[Dict]) -> None:
        """Save devices to cache"""
        try:
            # Retrieve old cache for comparison
            old_devices = []
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    old_cache_data = json.load(f)
                    old_devices = old_cache_data['devices']

            # Simplified data format
            simplified_devices = []
            for device in devices:
                simplified_device = {
                    'nom': device['device_name'],
                    'hote': device['host'],
                    'services': [s['service_name'] for s in device.get('services', [])],
                    'tags': [f"{tag['key']}:{tag['value']}" for tag in device.get('tags', [])],
                    'description': device.get('description', '')
                }
                simplified_devices.append(simplified_device)

            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'devices': simplified_devices
            }

            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"Cache saved ({len(devices)} machines)")

            # Compare with old cache
            if old_devices:
                old_device_names = {device['nom'] for device in old_devices}
                new_devices = [device for device in simplified_devices if device['nom'] not in old_device_names]

                if new_devices:
                    if len(new_devices) > 10:
                        logger.info(f"{len(new_devices)} new machines added")
                    else:
                        table = Table(show_header=True, header_style="bold magenta")
                        table.add_column("Name", style="cyan")
                        table.add_column("Host", style="green")
                        table.add_column("Services", style="yellow")
                        table.add_column("Tags", style="blue")
                        table.add_column("Description", style="white")

                        for device in new_devices:
                            services = ", ".join(device['services'])
                            tags = ", ".join(device['tags'])
                            description = device['description']
                            table.add_row(
                                device['nom'],
                                device['hote'],
                                services,
                                tags,
                                description
                            )

                        self.console.print(Panel.fit("[bold cyan]New machines added[/bold cyan]"))
                        self.console.print(table)

        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def authenticate(self) -> bool:
        """Authenticate to bastion"""
        if not self.password:
            self.password = getpass.getpass("Wallix password: ")
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                progress.add_task(description="Authenticating...")
                auth_response = self.session.post(
                    self.api_endpoint,
                    auth=HTTPBasicAuth(self.username, self.password),
                    verify=False,
                    timeout=10
                )
            return auth_response.status_code == 204
        except requests.exceptions.RequestException:
            return False

    def get_devices(self, force_refresh: bool = False) -> List[Dict]:
        """Retrieve list of devices"""
        if not force_refresh:
            cached_devices = self.load_cache(force_refresh)
            if cached_devices is not None:
                # Convert cache data to expected format
                return [{
                    'device_name': device['nom'],
                    'host': device['hote'],
                    'services': [{'service_name': s} for s in device['services']],
                    'tags': [{'key': t.split(':')[0], 'value': t.split(':')[1]} for t in device.get('tags', [])],
                    'description': device.get('description', '')
                } for device in cached_devices]

        logger.info("Retrieving all machines...")
        try:
            # Retrieve all machines in a single request
            devices_response = self.session.get(
                f"{self.devices_endpoint}?limit=-1",
                auth=HTTPBasicAuth(self.username, self.password),
                verify=False,
                timeout=10
            )

            if devices_response.status_code in [200, 206]:
                devices = devices_response.json()
                total_machines = len(devices)
                if force_refresh:
                    logger.info(f"Retrieval completed. Total: {total_machines} machines")
                else:
                    logger.info(f"Retrieval completed. Total: {total_machines} machines")
                self.save_cache(devices)
                return devices
            else:
                logger.error("Error retrieving machines")
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return []

    def get_service_icon(self, services: List[str]) -> str:
        """Returns appropriate icon based on services"""
        if "RDP" in services:
            return "🪟 "
        elif "SSH" in services:
            return "🐧 "
        return ""

    def display_devices(self, devices: List[Dict]) -> None:
        """Display list of devices in a table"""
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Host", style="green")
        table.add_column("Services", style="yellow")
        table.add_column("Tags", style="blue")
        table.add_column("Description", style="white")

        for device in devices:
            services = [s['service_name'] for s in device.get('services', [])]
            service_icon = self.get_service_icon(services)
            services_str = ", ".join(services)
            tags = ", ".join([f"{tag['key']}:{tag['value']}" for tag in device.get('tags', [])])
            description = device.get('description', '')
            table.add_row(
                f"{service_icon}{device['device_name']}",
                device['host'],
                services_str,
                tags,
                description
            )

        self.console.print(table)

    def update_history(self, device: Dict) -> None:
        """Update connection history"""
        try:
            history = []
            if self.history_file.exists():
                with open(self.history_file, 'r') as f:
                    history = json.load(f)

            # Check if machine is already in history
            existing_index = next(
                (i for i, h in enumerate(history) if h['device_name'] == device['device_name']),
                None
            )

            # Create entry for new connection
            new_entry = {
                'device_name': device['device_name'],
                'host': device['host'],
                'services': [s['service_name'] for s in device.get('services', [])],
                'tags': [f"{tag['key']}:{tag['value']}" for tag in device.get('tags', [])],
                'description': device.get('description', ''),
                'timestamp': datetime.now().isoformat()
            }

            if existing_index is not None:
                # If machine already exists, remove it from current position
                history.pop(existing_index)

            # Add new entry at the beginning of the list
            history.insert(0, new_entry)

            # Keep only the last 10 connections
            history = history[:10]

            with open(self.history_file, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Error updating history: {e}")

    def get_history(self) -> List[Dict]:
        """Retrieve connection history"""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error reading history: {e}")
        return []

    def display_history(self) -> None:
        """Display connection history"""
        history = self.get_history()
        if not history:
            logger.info("No connection history available")
            return

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="cyan")
        table.add_column("Host", style="green")
        table.add_column("Services", style="yellow")
        table.add_column("Tags", style="blue")
        table.add_column("Description", style="white")
        table.add_column("Last connection", style="blue")

        for i, device in enumerate(history, 1):
            services = device.get('services', [])
            service_icon = self.get_service_icon(services)
            services_str = ", ".join(services)
            tags = ", ".join(device.get('tags', []))
            description = device.get('description', '')
            last_connection = datetime.fromisoformat(device['timestamp']).strftime("%Y-%m-%d %H:%M")
            table.add_row(
                str(i),
                f"{service_icon}{device['device_name']}",
                device['host'],
                services_str,
                tags,
                description,
                last_connection
            )

        self.console.print(Panel.fit("[bold cyan]Recent connections[/bold cyan]"))
        self.console.print(table)
        self.console.print("\n[yellow]Enter the number of the machine to connect to (or 'q' to quit)[/yellow]")

        try:
            while True:
                try:
                    choice = input("Choice: ").strip()
                    if choice.lower() == 'q':
                        break

                    index = int(choice) - 1
                    if 0 <= index < len(history):
                        device = next(
                            (d for d in self.get_devices() if d['device_name'] == history[index]['device_name']),
                            None
                        )
                        if device:
                            self.connect_to_device(device)
                            break
                        else:
                            logger.error("Machine not found in current list")
                    else:
                        self.console.print("[red]Invalid number. Please try again.[/red]")
                except ValueError:
                    self.console.print("[red]Please enter a valid number.[/red]")
        except KeyboardInterrupt:
            print("\n")  # For a clean line break
            return

    def connect_to_device(self, device: Dict, interactive: bool = False, no_deploy: bool = False) -> None:
        """SSH connection to a device"""
        logger.info(f"Connecting to [bold blue]{device['device_name']}[/bold blue]...")
        self.update_history(device)

        # Prepare common commands
        script_dir = Path.home() / '.sshtools'
        
        # Determine username
        username = "Interactive" if interactive else self.username

        # Build SSH command
        if no_deploy:
            # Standard SSH connection
            ssh_command = f"ssh -tt -A -p 22 {username}@{device['device_name']}:SSH:{self.username}@{self.bastion_host}"
        elif interactive:
            # Simple interactive mode
            ssh_command = f"ssh -tt -A -p 22 {username}@{device['device_name']}:SSH:{self.username}@{self.bastion_host}"
        else:
            # Normal mode or interactive mode with file deployment
            try:
                # Prepare files in compressed base64
                files_content = []
                deploy_files = WALLIX_DEPLOY_FILES if WALLIX_DEPLOY_FILES else []
                
                for filename in deploy_files:
                    try:
                        with open(script_dir / filename, 'rb') as f:
                            content = f.read()
                            content_gzip = gzip.compress(content)
                            content_base64 = base64.b64encode(content_gzip).decode('utf-8')
                            files_content.append(('/tmp/' + filename, content_base64))
                    except FileNotFoundError as e:
                        logger.error(f"File not found: {e}")
                        continue

                if files_content:
                    # Build deployment command
                    deploy_cmd = " && ".join([
                        f"echo '{content}' | base64 -d | gunzip > {filename}"
                        for filename, content in files_content
                    ])
                    # If .bashrc_remote is in the deploy files list, use it as rcfile
                    has_bashrc = '.bashrc_remote' in deploy_files
                    if has_bashrc:
                        deploy_cmd += " && bash --rcfile /tmp/.bashrc_remote"
                    else:
                        deploy_cmd += " && bash -l"
                else:
                    deploy_cmd = "bash -l"

                ssh_command = f"ssh -tt -A -p 22 {username}@{device['device_name']}:SSH:{self.username}@{self.bastion_host} '{deploy_cmd}'"
            except Exception as e:
                logger.error(f"Error deploying files: {e}")
                ssh_command = f"ssh -tt -A -p 22 {username}@{device['device_name']}:SSH:{self.username}@{self.bastion_host} 'bash -l'"

        subprocess.run(ssh_command, shell=True)

    def update_device(self, device_name: str, description: str = None, tags: str = None) -> bool:
        """Update device description and tags"""
        try:
            # Authentication required for update
            if not self.authenticate():
                logger.error("Authentication error")
                return False

            # Retrieve device
            devices = self.get_devices()
            device = next(
                (d for d in devices if d['device_name'] == device_name),
                None
            )

            if not device:
                logger.error(f"Device '{device_name}' not found")
                return False

            # Prepare update data with only necessary fields
            update_data = {
                'device_name': device['device_name'],
                'host': device['host']
            }

            if description is not None:
                update_data['description'] = description
            else:
                update_data['description'] = device.get('description', '')

            if tags is not None:
                # Convert tags from "key1:value1,key2:value2" format to expected format
                update_data['tags'] = [
                    {'key': tag.split(':')[0], 'value': tag.split(':')[1]}
                    for tag in tags.split(',')
                ]
            else:
                update_data['tags'] = device.get('tags', [])

            # Update device using PUT
            response = self.session.put(
                f"{self.devices_endpoint}/{device_name}",
                auth=HTTPBasicAuth(self.username, self.password),
                json=update_data,
                verify=False,
                timeout=10
            )

            if response.status_code in [200, 204]:
                logger.info(f"Device '{device_name}' updated successfully")
                # Refresh cache
                self.get_devices(force_refresh=True)
                return True
            else:
                logger.error(f"Error updating device: {response.status_code}")
                logger.error(f"API response: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error updating device: {e}")
            return False

    def search_devices(self, query: str = None, filter_regex: str = None, filter_services: str = None, filter_tags: str = None, interactive: bool = False, no_deploy: bool = False) -> List[Dict]:
        """Search devices by name or host with optional filters"""
        devices = self.get_devices()
        if not query and not filter_regex and not filter_services and not filter_tags:
            return devices

        results = devices

        # Filter by regex if specified
        if filter_regex:
            import re
            pattern = re.compile(filter_regex, re.IGNORECASE)
            results = [d for d in results if pattern.search(d['device_name']) or pattern.search(d['host']) or pattern.search(d.get('description', ''))]

        # Filter by services if specified
        if filter_services:
            required_services = [s.strip().upper() for s in filter_services.split(',')]
            results = [d for d in results if all(s in [service['service_name'].upper() for service in d.get('services', [])] for s in required_services)]

        # Filter by tags if specified
        if filter_tags:
            required_tags = [t.strip().lower() for t in filter_tags.split(',')]
            results = [d for d in results if all(t in [tag.lower() for tag in d.get('tags', [])] for t in required_tags)]

        # Filter by query if specified
        if query:
            results = [
                device for device in results
                if query.lower() in device['device_name'].lower() or
                query.lower() in device['host'].lower() or
                query.lower() in device.get('description', '').lower()
            ]

        if results:
            self.console.print(Panel.fit(f"[bold cyan]Search results[/bold cyan]"))

            if len(results) == 1:
                self.display_devices(results)
                self.console.print("\n[yellow]Press Enter to connect or 'n' to cancel[/yellow]")
                response = input().lower()
                if response != 'n':
                    self.connect_to_device(results[0], interactive, no_deploy)
            else:
                # Create interactive table
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("#", style="dim", width=3)
                table.add_column("Name", style="cyan")
                table.add_column("Host", style="green")
                table.add_column("Services", style="yellow")
                table.add_column("Tags", style="blue")
                table.add_column("Description", style="white")

                for i, device in enumerate(results, 1):
                    services = [s['service_name'] for s in device.get('services', [])]
                    service_icon = self.get_service_icon(services)
                    services_str = ", ".join(services)
                    tags = ", ".join([f"{tag['key']}:{tag['value']}" for tag in device.get('tags', [])])
                    description = device.get('description', '')
                    table.add_row(
                        str(i),
                        f"{service_icon}{device['device_name']}",
                        device['host'],
                        services_str,
                        tags,
                        description
                    )

                self.console.print(table)
                self.console.print("\n[yellow]Enter the number of the machine to connect to (or 'q' to quit)[/yellow]")

                while True:
                    try:
                        choice = input("Choice: ").strip()
                        if choice.lower() == 'q':
                            break

                        index = int(choice) - 1
                        if 0 <= index < len(results):
                            self.connect_to_device(results[index], interactive, no_deploy)
                            break
                        else:
                            self.console.print("[red]Invalid number. Please try again.[/red]")
                    except ValueError:
                        self.console.print("[red]Please enter a valid number.[/red]")
        else:
            logger.error("No devices found")
            self.console.print("\n[yellow]Do you want to force cache refresh and try again? (y/n)[/yellow]")
            response = input().lower() or 'y'  # 'y' by default if empty
            if response == 'y':
                if not self.authenticate():
                    logger.error("Authentication error")
                    return
                devices = self.get_devices(force_refresh=True)
                results = self.search_devices(query, filter_regex, filter_services, filter_tags, interactive, no_deploy)
                if results:
                    self.console.print(Panel.fit(f"[bold cyan]Search results[/bold cyan]"))
                    if len(results) == 1:
                        self.display_devices(results)
                        self.console.print("\n[yellow]Press Enter to connect or 'n' to cancel[/yellow]")
                        response = input().lower()
                        if response != 'n':
                            self.connect_to_device(results[0], interactive, no_deploy)
                    else:
                        # Create interactive table
                        table = Table(show_header=True, header_style="bold magenta")
                        table.add_column("#", style="dim", width=3)
                        table.add_column("Name", style="cyan")
                        table.add_column("Host", style="green")
                        table.add_column("Services", style="yellow")
                        table.add_column("Tags", style="blue")
                        table.add_column("Description", style="white")

                        for i, device in enumerate(results, 1):
                            services = [s['service_name'] for s in device.get('services', [])]
                            service_icon = self.get_service_icon(services)
                            services_str = ", ".join(services)
                            tags = ", ".join([f"{tag['key']}:{tag['value']}" for tag in device.get('tags', [])])
                            description = device.get('description', '')
                            table.add_row(
                                str(i),
                                f"{service_icon}{device['device_name']}",
                                device['host'],
                                services_str,
                                tags,
                                description
                            )

                        self.console.print(table)
                        self.console.print("\n[yellow]Enter the number of the machine to connect to (or 'q' to quit)[/yellow]")

                        while True:
                            try:
                                choice = input("Choice: ").strip()
                                if choice.lower() == 'q':
                                    break

                                index = int(choice) - 1
                                if 0 <= index < len(results):
                                    self.connect_to_device(results[index], interactive, no_deploy)
                                    break
                                else:
                                    self.console.print("[red]Invalid number. Please try again.[/red]")
                            except ValueError:
                                self.console.print("[red]Please enter a valid number.[/red]")
                else:
                    logger.error("No devices found after refresh")

        return results

def main():
    try:
        parser = argparse.ArgumentParser(description="Wallix connection manager")
        parser.add_argument(
            "-s", "--search",
            help="Search for a machine by name",
            type=str
        )
        parser.add_argument(
            "-l", "--list",
            help="List all machines",
            action="store_true"
        )
        parser.add_argument(
            "--filter",
            help="Filter machines by regular expression",
            type=str
        )
        parser.add_argument(
            "--services",
            help="Filter machines by services (e.g., SSH,RDP)",
            type=str
        )
        parser.add_argument(
            "--tags",
            help="Filter machines by tags (e.g., production,test)",
            type=str
        )
        parser.add_argument(
            "-c", "--connect",
            help="Connect directly to a machine",
            type=str
        )
        parser.add_argument(
            "-f", "--force-refresh",
            help="Force cache refresh",
            action="store_true"
        )
        parser.add_argument(
            "-i", "--interactive",
            help="Use Interactive account for connection",
            action="store_true"
        )
        parser.add_argument(
            "-u", "--update",
            help="Update machine description and tags",
            type=str
        )
        parser.add_argument(
            "--description",
            help="New description for the machine (used with --update)",
            type=str
        )
        parser.add_argument(
            "--new-tags",
            help="New tags for the machine in format key1:value1,key2:value2 (used with --update)",
            type=str
        )
        parser.add_argument(
            "-n", "--no-deploy",
            help="Standard SSH connection without file deployment (no bashrc, vimrc, etc.)",
            action="store_true"
        )
        parser.add_argument(
            "search_term",
            nargs="?",
            help="Search term (used without option)",
            type=str
        )

        args = parser.parse_args()
        manager = WallixManager()

        # If a search term is provided without option, treat it as a search
        if args.search_term and not any([args.list, args.connect, args.search, args.force_refresh, args.update]):
            args.search = args.search_term

        # If no action is specified, display history
        if not any([args.list, args.connect, args.search, args.force_refresh, args.update]):
            manager.display_history()
            sys.exit(0)

        # Authentication only needed if forcing refresh or updating
        if args.force_refresh or args.update:
            if not manager.authenticate():
                logger.error("Authentication error")
                sys.exit(1)

        # Update a device
        if args.update:
            if not args.description and not args.new_tags:
                logger.error("At least one of --description or --new-tags must be specified with --update")
                sys.exit(1)
            manager.update_device(args.update, args.description, args.new_tags)
            sys.exit(0)

        # Force cache refresh
        if args.force_refresh:
            devices = manager.get_devices(force_refresh=True)
            if args.search:
                manager.search_devices(args.search, args.filter, args.services, args.tags, args.interactive, args.no_deploy)
            elif args.list:
                manager.display_devices(devices)
            sys.exit(0)

        if args.list:
            devices = manager.get_devices(args.force_refresh)

            # Filter by regex if specified
            if args.filter:
                import re
                pattern = re.compile(args.filter, re.IGNORECASE)
                devices = [d for d in devices if pattern.search(d['device_name']) or pattern.search(d['host']) or pattern.search(d.get('description', ''))]

            # Filter by services if specified
            if args.services:
                required_services = [s.strip().upper() for s in args.services.split(',')]
                devices = [d for d in devices if all(s in [service['service_name'].upper() for service in d.get('services', [])] for s in required_services)]

            # Filter by tags if specified
            if args.tags:
                required_tags = [t.strip().lower() for t in args.tags.split(',')]
                devices = [d for d in devices if all(t in [tag.lower() for tag in d.get('tags', [])] for t in required_tags)]

            manager.console.print(Panel.fit("[bold cyan]Available machines list[/bold cyan]"))
            manager.display_devices(devices)

        elif args.connect:
            devices = manager.get_devices(args.force_refresh)
            device = next(
                (d for d in devices if d['device_name'] == args.connect),
                None
            )
            if device:
                manager.connect_to_device(device, args.interactive, args.no_deploy)
            else:
                logger.error(f"Machine '{args.connect}' not found")
                logger.info("Do you want to force cache refresh and try again? (y/n)")
                response = input().lower() or 'y'  # 'y' by default if empty
                if response == 'y':
                    if not manager.authenticate():
                        logger.error("Authentication error")
                        sys.exit(1)
                    devices = manager.get_devices(force_refresh=True)
                    device = next(
                        (d for d in devices if d['device_name'] == args.connect),
                        None
                    )
                    if device:
                        manager.connect_to_device(device, args.interactive, args.no_deploy)
                    else:
                        logger.error("Machine not found after refresh")
        elif args.search:
            # Interactive mode by default with filters
            manager.search_devices(args.search, args.filter, args.services, args.tags, args.interactive, args.no_deploy)
        else:
            # Interactive mode by default
            manager.search_devices(None, args.filter, args.services, args.tags, args.interactive, args.no_deploy)
    except KeyboardInterrupt:
        print("\n")  # For a clean line break
        sys.exit(0)

if __name__ == "__main__":
    main()
