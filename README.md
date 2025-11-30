<p align="center">
  <a href="https://mickaelasseline.com">
    <img src="https://zupimages.net/up/20/04/7vtd.png" width="140px" alt="PAPAMICA" />
  </a>
</p>

<p align="center">
  <a href="#"><img src="https://readme-typing-svg.herokuapp.com?center=true&vCenter=true&lines=Wallix+SSH;"></a>
</p>
<div align="center">
A command-line tool to easily manage and connect to machines via the Wallix bastion from terminal.
Use with : https://www.wallix.com/
</div>

## Features

- 🔍 Interactive machine search
- 📋 List machines with filters (services, tags, regex)
- 🔄 Local cache of machines for optimal performance
- 📝 History of recent connections
- 🔑 Support for interactive connections
- 🏷️ Manage machine tags and descriptions
- 🎨 Rich and colorful user interface

## --help
```bash
usage: wallix_ssh.py [-h] [-s SEARCH] [-l] [--filter FILTER] [--services SERVICES] [--tags TAGS] [-c CONNECT] [-f] [-i] [-u UPDATE] [--description DESCRIPTION] [--new-tags NEW_TAGS] [-n] [search_term]

Wallix connection manager

positional arguments:
  search_term           Search term (used without option)

options:
  -h, --help                show this help message and exit
  -s, --search SEARCH       Search for a machine by name
  -l, --list                List all machines
  --filter FILTER           Filter machines by regular expression
  --services SERVICES       Filter machines by services (e.g., SSH,RDP)
  --tags TAGS               Filter machines by tags (e.g., production,test)
  -c, --connect CONNECT     Connect directly to a machine
  -f, --force-refresh       Force cache refresh
  -i, --interactive         Use Interactive account for connection
  -u, --update UPDATE       Update machine description and tags
  --description DESCRIPTION New description for the machine (used with --update)
  --new-tags NEW_TAGS       New tags for the machine in format key1:value1,key2:value2 (used with --update)
  -n, --no-deploy           Standard SSH connection without file deployment (no bashrc, vimrc, etc.)
```

## Prerequisites

- Python 3.7+
- sshtools : https://github.com/PAPAMICA/sshtools (facultatif)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd wallix-ssh-public
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

The script uses a `config.ini` file for configuration. Create this file in the script directory with the following structure:

```ini
[wallix]
# Wallix Bastion base URL
base_url = https://bastion.papamica.com

# Wallix username for authentication
username = your.username

# Wallix password (leave empty to be prompted)
password = 

# Cache file path (leave empty to use default: ~/.wallix_cache)
# Can use absolute path or path relative to home directory (e.g., ~/.cache/wallix/cache)
cache_file = 

# Files to deploy on remote server at connection (comma-separated list)
# Files should be located in ~/.sshtools/ directory
# Example: .bashrc_remote,.vimrc_remote,.webshare.py
# Leave empty to disable file deployment
deploy_files = 
```

**Important**: The `config.ini` file must be created before running the script. You can copy the provided `config.ini` template and fill in your values.

## Usage

### Basic commands

```bash
# Display connection history
./wallix_ssh.py

# Search for a machine
./wallix_ssh.py -s "machine_name"

# List all machines
./wallix_ssh.py -l

# Connect directly to a machine
./wallix_ssh.py -c "machine_name"

# Force cache refresh
./wallix_ssh.py -f
```

### Advanced options

```bash
# Filter by regular expression
./wallix_ssh.py --filter "pattern"

# Filter by services
./wallix_ssh.py --services "SSH,RDP"

# Filter by tags
./wallix_ssh.py --tags "production,test"

# Interactive mode (use Interactive account)
./wallix_ssh.py -i

# Update machine description
./wallix_ssh.py -u "machine_name" --description "New description"

# Update machine tags
./wallix_ssh.py -u "machine_name" --new-tags "env:prod,role:web"

# Standard SSH connection without file deployment
./wallix_ssh.py -n
```

## Examples

1. Search for a production machine with SSH:
```bash
./wallix_ssh.py --services SSH --tags production
```

2. Interactive connection to a web machine:
```bash
./wallix_ssh.py -i --tags web
```

3. Update a machine:
```bash
./wallix_ssh.py -u "web-server-01" --description "Main web server" --new-tags "env:prod,role:web,version:2.0"
```

## File structure

The script creates and uses the following files in the user's home directory:

- `~/.wallix_cache` : Machine cache
- `~/.wallix_history` : Connection history
- `~/.sshtools/` : Directory containing SSH configuration files (facultatif)

## Contributing

Contributions are welcome! Feel free to open an issue or a pull request.
