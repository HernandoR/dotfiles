
#!/usr/bin/env bash

# This is a shell script that provides functionality to backup, update, and restore dotfiles using
# rsync. It also includes options for installing zsh and Oh My Zsh. The script uses command-line
# options to determine which subcommand to execute and includes functions for pre-processing and
# post-processing logic.

# Default values
help=false
quiet=false
install_omz=false

# get the current directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"



#------------------------------------------------------------------------------


function pre_process() {
	# Script logic based on the options
	if $help; then
		exit 0
	fi

	if $quiet; then
		echo "Running in quiet mode"
	fi

	# cd "$(dirname "${BASH_SOURCE}")";

	# git pull origin main;



	#------------------------------------------------------------------------------

	# if havent install zsh, install it first
	if ! command -v zsh &> /dev/null
	then
		echo "zsh could not be found"
		echo "installing zsh"
		sudo apt -y install zsh
		echo "zsh installed please run this script again"
		exit 1
	fi
}


# Function to back up dotfiles using rsync
backup_dotfiles() {
    # Accept source directory and backup directory as parameters
    source_dir="$1"
    backup_dir="$2"

    # Ensure the backup directory exists
    mkdir -p "$backup_dir"

    # Perform the backup using rsync
	rsync --exclude ".git*" \
		--exclude ".DS_Store" \
		--exclude ".osx" \
		--exclude "bootstrap.sh" \
		--exclude "README.md" \
		--exclude "LICENSE-MIT.txt" \
        --exclude ".z" \
        --exclude ".zcompdump*" \
        --exclude "*history*" \
        --include ".vim/" \
        --exclude "*/" \
		-avuh --no-perms "$source_dir" "$backup_dir"

    echo "Dotfiles backup complete!"
}

# Function to restore dotfiles backup
restore_dotfiles() {
    # Accept backup directory and destination directory as parameters
    backup_dir="$1"
    restore_dir="$2"

    backup_dotfiles "$restore_dir" "./bkp/$restore_dir.bkp"

    # Perform the restore using rsync
	rsync --exclude ".git*" \
		--exclude ".DS_Store" \
		--exclude ".osx" \
		--exclude "bootstrap.sh" \
		--exclude "README.md" \
		--exclude "LICENSE-MIT.txt" \
        --exclude ".z" \
        --exclude ".zcompdump*" \
        --exclude "*history*" \
        --include ".vim/" \
        --exclude "*/" \
		-avh --no-perms "$backup_dir" "$restore_dir"

    echo "Dotfiles restore complete!"
}



# function doIt() {
# 	rsync --exclude ".git/" \
# 		--exclude ".DS_Store" \
# 		--exclude ".osx" \
# 		--exclude "bootstrap.sh" \
# 		--exclude "README.md" \
# 		--exclude "LICENSE-MIT.txt" \
# 		-avh --no-perms ./sources/root ~;
	
# }


# if [ $quiet ]; then
# 	doIt;
# else
# 	read -p "This may overwrite existing files in your home directory. Are you sure? (y/n) " -n 1;
# 	echo "";
# 	if [[ $REPLY =~ ^[Yy]$ ]]; then
# 		doIt;
# 	fi;
    
# fi;

# Function for backup subcommand
do_backup() {
    echo "Performing backup..."
    # Add backup logic here
    pre_process;
    backup_dotfiles $HOME/ ./sources/root/ ;
    post_process;
}

# Function for update subcommand
do_update() {
    echo "deperectated, use backup..."
    # Add update logic here
    # pre_process;
    # backup_dotfiles ./sources/root $HOME;
    # post_process ;
}

# Function for restore subcommand
do_restore() {
    echo "Performing restore..."
    # Add restore logic here
    pre_process;
    restore_dotfiles ./sources/root/ $HOME ;
    post_process;
}

post_process(){
	
	if $install_omz; then
		echo "Installing Oh My Zsh"
		# Add your installation logic here
		zsh -c "$DIR/config-ohmyzsh.sh"
	fi

}



#------------------------------------------------------------------------------



# Parsing command-line options
while getopts ":hq-:" opt; do
    case $opt in
        h | -help )
            help=true
            usage
            exit 0
            ;;
        q | -quiet )
            quiet=true
            ;;
        d | -dry )
            dry_run=true
            ;;
        - )
            case "${OPTARG}" in
                help )
                    help=true
                    usage
                    exit 0
                    ;;
                quiet )
                    quiet=true
                    ;;
                install-omz )
                    install_omz=true
                    ;;
                * )
                    echo "Invalid option: --${OPTARG}"
                    usage
                    exit 1
                    ;;
            esac
            ;;
        : )
            echo "Option requires an argument: -$OPTARG"
            usage
            exit 1
            ;;
        \? )
            echo "Invalid option: -$OPTARG"
            usage
            exit 1
            ;;
    esac
done

# Main script logic
if [[ $# -eq 0 ]]; then
    usage
    exit 1
fi

case "$1" in
    backup )
        do_backup
        ;;
    update )
        do_update
        ;;
    restore )
        do_restore
        ;;
    * )
        echo "Invalid subcommand: $1"
        echo "Usage: script.sh [backup|update|restore]"
        exit 1
        ;;
esac