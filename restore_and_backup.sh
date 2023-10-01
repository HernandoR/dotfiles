#!bash
# This is a shell script that provides functionality to backup, update, and restore dotfiles using
# rsync. It also includes options for installing zsh and Oh My Zsh. The script uses command-line
# options to determine which subcommand to execute and includes functions for pre-processing and
# post-processing logic.

# Default values
help=false
quiet=false
install_omz=false
dry_run=false

# get the current directory
# DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"


rsync_default_options="avhC"

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
    dest_dir="$2"

    # Ensure the backup directory exists
    mkdir -p "$dest_dir"

    echo $ignore_single_file_cmd

    # Perform the backup using rsync
    
	rsync \
        --files-from="./sources/.file_list" \
        --exclude-from="./sources/.ex_list" \
		-$rsync_default_options \
        --no-perms \
        "$source_dir" "$dest_dir"
    echo $rsync_cmd
    echo "Dotfiles backup complete!"
}

# Function to restore dotfiles backup
restore_dotfiles() {
    # Accept backup directory and destination directory as parameters
    backup_dir="$1"
    restore_dir="$2"

    backup_dotfiles "$restore_dir" "./bkp/$restore_dir.bkp"

    # Perform the restore using rsync
	rsync \
        --files-from="./sources/.file_list" \
        --exclude-from="./sources/.ex_list" \
		-$rsync_default_options \
        --no-perms \
        "$backup_dir" "$restore_dir"

    echo "Dotfiles restore complete!"
}


# Function for backup subcommand
do_backup() {
    echo "Performing backup..."
    echo "opts $rsync_default_options"
    if [ ! $quiet ];
    then
        echo "continue? y/n"
        read -n 1 -r
        if [[ $REPLY == [nN]$ ]]
        then
            exit 1
        fi
    fi

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
    echo "opts $rsync_default_options"
    pre_process;
    restore_dotfiles ./sources/root/ $HOME ;
    post_process;
}

post_process(){
	
	if $install_omz; then
		echo "Installing Oh My Zsh"
		# Add your installation logic here
		zsh -c "./config-ohmyzsh.sh"
	fi

}

# function for help 
usage(){
    echo "usage havent implement yet"
}


#------------------------------------------------------------------------------


# Default values for options
quiet=false
verbose=false
dry_run=false

phase_args(){
    # Args handding
    while getopts ":hvqd-" opt; do # Go through the options

        case $opt in
            h ) # Help
                usage
                exit 0 # Exit correctly
            ;;
            v ) # Debug
                echo "Read verbose flag"
                verbose=true
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
            ? ) # Invalid option
                echo "[ERROR]: Invalid option: -${OPTARG}"
                usage
                exit 1 # Exit with erro
            ;;
        esac
    done
    echo "dry_run: $dry_run"
    if $dry_run; then
        rsync_default_options+="n"
    fi
}

if [ ! 0 == $# ] # If options provided then 
then
    subcommand=$1; shift # Get subcommand and shift to next option
    # subcmd handling
    case "$subcommand" in
        backup )
                unset OPTIND # in order to make -v pow -a <arg> -f <arg> work -> https://stackoverflow.com/questions/2189281/how-to-call-getopts-in-bash-multiple-times
                if [ ! 0 == $# ] # if options provided
                then
                    if [ $verbose == true ]; then echo "Remaining args are: <${@}>"; fi
                    phase_args "$@"
                fi

                do_backup
            ;;
        update )
            do_update
            ;;
        restore )
            unset OPTIND # in order to make -v pow -a <arg> -f <arg> work -> https://stackoverflow.com/questions/2189281/how-to-call-getopts-in-bash-multiple-times
                if [ ! 0 == $# ] # if options provided
                then
                    if [ $verbose == true ]; then echo "Remaining args are: <${@}>"; fi
                    phase_args "$@"
                fi

            do_restore
            ;;
        * ) # Invalid subcommand
            if [ ! -z $subcommand ]; then  # Don't show if no subcommand provided
                echo "Invalid subcommand: $subcommand"
            fi
            usage
            exit 1 # Exit with error
        ;;
    esac
else # else if no options provided throw error
    usage
    exit 1
fi
