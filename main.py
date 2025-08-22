import subprocess
import sys
import os
import shutil
import stat

def is_container() -> bool:
    return os.path.exists("/.dockerenv") or os.path.exists("/var/run/secrets/kubernetes.io")

def is_ci_environment() -> bool:
    """Check if running in a CI environment"""
    ci_indicators = [
        'CI', 'CONTINUOUS_INTEGRATION', 'GITHUB_ACTIONS', 
        'JENKINS_URL', 'TRAVIS', 'CIRCLECI', 'GITLAB_CI'
    ]
    return any(os.getenv(indicator) for indicator in ci_indicators)

def should_skip_venv() -> bool:
    """Check if venv should be skipped"""
    return '--no-venv' in sys.argv or is_container() or is_ci_environment()

# Handle venv setup
if sys.prefix == sys.base_prefix and not should_skip_venv():
    print("Running the bot in a venv (virtual environment) to avoid dependency conflicts.")
    print("Note: You can skip venv creation with the --no-venv argument if needed.")
    venv_path = "bot_venv"

    # Determine the python executable path in the venv
    if sys.platform == "win32":
        venv_python_name = os.path.join(venv_path, "Scripts", "python.exe")
        activate_script = os.path.join(venv_path, "Scripts", "activate.bat")
    else:
        venv_python_name = os.path.join(venv_path, "bin", "python")
        activate_script = os.path.join(venv_path, "bin", "activate")

    if not os.path.exists(venv_path):
        try:
            print("Attempting to create virtual environment automatically...")
            subprocess.check_call([sys.executable, "-m", "venv", venv_path], timeout=300)
            print(f"Virtual environment created at {venv_path}")

            if sys.platform == "win32":
                print("\nVirtual environment created.")
                print("To continue, please run the script again with the venv Python:")
                print(f"  1. Ensure CMD or PowerShell is open in this directory: {os.getcwd()}")
                print(f"  2. Run this exact command: {venv_python_name} {os.path.basename(sys.argv[0])}")
                sys.exit(0)
            else: # For non-Windows, try to relaunch automatically
                print("Restarting script in virtual environment...")
                venv_python_executable = os.path.join(venv_path, "bin", "python")
                os.execv(venv_python_executable, [venv_python_executable] + sys.argv)

        except Exception as e:
            print("Failed to create virtual environment automatically.")
            print(f"Error: {e}")
            print("Please create one manually with: python -m venv bot_venv")
            print("Then activate it and run this script again.")
            print("See also: https://docs.python.org/3/library/venv.html#how-venvs-work")
            sys.exit(1)
    else: # Venv exists
        if sys.platform == "win32":
            print(f"Virtual environment at {venv_path} exists.")
            print("To ensure you are using it, please run the script with the venv Python:")
            print(f"  1. Ensure CMD or PowerShell is open in this directory: {os.getcwd()}")
            print(f"  2. Run this exact command: {venv_python_name} {os.path.basename(sys.argv[0])}")
            sys.exit(0)
        elif '--no-venv' in sys.argv:
            print("Virtual environment setup skipped due to --no-venv flag.")
            print("Warning: Dependencies will be installed system-wide which may cause conflicts.")
        else: # For non-Windows, if venv exists but we're not in it, try to relaunch
            venv_python_executable = os.path.join(venv_path, "bin", "python")
            if os.path.exists(venv_python_executable):
                print(f"Using existing virtual environment at {venv_path}. Restarting...")
                os.execv(venv_python_executable, [venv_python_executable] + sys.argv)
            else:
                print(f"Virtual environment at {venv_path} appears corrupted.")
                print("Please remove it and run the script again, or create a new one manually.")
                sys.exit(1)

try: # Import or install requests so we can get the requirements
    import requests
except ImportError:
    print("Installing requests (required for dependency management)...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"], 
                            timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import requests
    except Exception as e:
        print(f"Failed to install requests: {e}")
        print("Please install requests manually: pip install requests")
        sys.exit(1)

def remove_readonly(func, path, _):
    """Clear the readonly bit and reattempt the removal"""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def safe_remove(path, is_dir=None):
    """
    Safely remove a file or directory.
    Clear the read-only bit on Windows.
    
    Args:
        path: Path to file or directory to remove
        is_dir: True for directory, False for file, None to auto-detect
        
    Returns:
        bool: True if successfully removed, False otherwise
    """
    if not os.path.exists(path):
        return True  # Already gone, consider it success
    
    if is_dir is None: # Auto-detect type if not specified
        is_dir = os.path.isdir(path)
    
    try:
        if is_dir:
            if sys.platform == "win32":
                shutil.rmtree(path, onexc=remove_readonly)
            else:
                shutil.rmtree(path)
        else:
            try:
                os.remove(path)
            except PermissionError:
                if sys.platform == "win32":
                    os.chmod(path, stat.S_IWRITE)
                    os.remove(path)
                else:
                    raise  # Re-raise on non-Windows platforms
        
        return True
        
    except PermissionError:
        print(f"Warning: Access Denied. Could not remove '{path}'.\nCheck permissions or if {'directory' if is_dir else 'file'} is in use.")
    except OSError as e:
        print(f"Warning: Could not remove '{path}': {e}")
    
    return False

def calculate_file_hash(filepath):
    """Calculate SHA256 hash of a file."""
    import hashlib
    if not os.path.exists(filepath):
        return None
    
    sha256_hash = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception:
        return None

def get_removed_packages():
    """Compare old and new requirements to find removed packages"""
    if not os.path.exists("requirements.old") or not os.path.exists("requirements.txt"):
        return []
    
    old_packages = set()
    new_packages = set()
    
    try:
        # Parse old requirements
        with open("requirements.old", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0]
                    old_packages.add(pkg_name.strip().lower())
        
        # Parse new requirements
        with open("requirements.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0]
                    new_packages.add(pkg_name.strip().lower())
        
        return list(old_packages - new_packages)
    except Exception as e:
        print(F.YELLOW + f"Error comparing requirements: {e}" + R)
        return []

def cleanup_removed_packages():
    """Uninstall packages that were removed from requirements"""
    # If no requirements.old exists, this might be an upgrade from legacy version
    if not os.path.exists("requirements.old"):
        cleanup_legacy_packages()
        return
    
    removed = get_removed_packages()
    
    if removed:
        print_status(f"Found {len(removed)} packages removed from requirements: {', '.join(removed)}", "warning", indent=1)
        
        debug_mode = "--verbose" in sys.argv or "--debug" in sys.argv
        
        for package in removed:
            try:
                cmd = [sys.executable, "-m", "pip", "uninstall", "-y", package]
                
                if debug_mode:
                    subprocess.check_call(cmd, timeout=300)
                else:
                    subprocess.check_call(cmd, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print_status(f"Removed {package}", "success", indent=2)
            except subprocess.CalledProcessError:
                print_status(f"Could not remove {package} (might be needed by other packages)", "warning", indent=2)
            except Exception as e:
                print_status(f"Error removing {package}: {e}", "error", indent=2)
    
    try:
        if os.path.exists("requirements.old"):
            os.remove("requirements.old")
    except:
        pass

# Potential leftovers from older bot versions
LEGACY_PACKAGES_TO_REMOVE = [
    "ddddocr",
    "easyocr", 
    "torch",
    "torchvision",
    "torchaudio",
    "opencv-python",
    "opencv-python-headless",
]

def is_package_installed(package_name):
    """Check if a package is installed"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False

def cleanup_legacy_packages():
    """Remove known obsolete packages from older bot versions"""
    debug_mode = "--verbose" in sys.argv or "--debug" in sys.argv
    removed_count = 0
    found_packages = []
    
    for package in LEGACY_PACKAGES_TO_REMOVE:
        if is_package_installed(package):
            found_packages.append(package)
    
    if found_packages:
        print_status(f"Legacy packages found: {', '.join(found_packages)}", "warning", indent=1)
        print_status("Removing legacy packages...", "arrow", indent=1)
        
        for package in found_packages:
            try:
                cmd = [sys.executable, "-m", "pip", "uninstall", "-y", package]
                
                if debug_mode:
                    subprocess.check_call(cmd, timeout=300)
                else:
                    subprocess.check_call(cmd, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                print_status(f"Removed {package}", "success", indent=2)
                removed_count += 1
            except subprocess.CalledProcessError:
                print_status(f"Could not remove {package} (might be needed by other packages)", "warning", indent=2)
            except Exception as e:
                print_status(f"Error removing {package}: {e}", "error", indent=2)
        
    return removed_count

# Configuration for multiple update sources
UPDATE_SOURCES = [
    {
        "name": "GitHub",
        "api_url": "https://api.github.com/repos/whiteout-project/bot-dev/releases/latest",
        "primary": True
    },
    {
        "name": "GitLab",
        "api_url": "https://gitlab.whiteout-bot.com/api/v4/projects/1/releases",
        "project_id": 1,
        "primary": False
    }
    # Can add more sources here as needed
]

def get_latest_release_info(beta_mode=False):
    """Try to get latest release info from multiple sources."""
    for source in UPDATE_SOURCES:
        try:
            if source['name'] == "GitHub":
                if beta_mode:
                    # Get latest commit from main branch
                    repo_name = source['api_url'].split('/repos/')[1].split('/releases')[0]
                    branch_url = f"https://api.github.com/repos/{repo_name}/branches/main"
                    response = requests.get(branch_url, timeout=30)
                    if response.status_code == 200:
                        data = response.json()
                        commit_sha = data['commit']['sha'][:7]  # Short SHA
                        return {
                            "tag_name": f"beta-{commit_sha}",
                            "body": f"Latest development version from main branch (commit: {commit_sha})",
                            "download_url": f"https://github.com/{repo_name}/archive/refs/heads/main.zip",
                            "source": f"{source['name']} (Beta)"
                        }
                else:
                    response = requests.get(source['api_url'], timeout=30)
                    if response.status_code == 200:
                        data = response.json()
                        # Use GitHub's automatic source archive
                        repo_name = source['api_url'].split('/repos/')[1].split('/releases')[0]
                        download_url = f"https://github.com/{repo_name}/archive/refs/tags/{data['tag_name']}.zip"
                        return {
                            "tag_name": data["tag_name"],
                            "body": data["body"],
                            "download_url": download_url,
                            "source": source['name']
                        }
                    
            elif source['name'] == "GitLab":
                response = requests.get(source['api_url'], timeout=30)
                if response.status_code == 200:
                    releases = response.json()
                    if releases:
                        latest = releases[0]  # GitLab returns array, first is latest
                        tag_name = latest['tag_name']
                        # Use GitLab's source archive
                        download_url = f"https://gitlab.whiteout-bot.com/whiteout-project/bot/-/archive/{tag_name}/bot-{tag_name}.zip"
                        return {
                            "tag_name": tag_name,
                            "body": latest.get("description", "No release notes available"),
                            "download_url": download_url,
                            "source": source['name']
                        }
            
            # Add handling for other sources here
            
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    print(f"{source['name']} repository not found or unavailable")
                elif e.response.status_code in [403, 429]:
                    print(f"{source['name']} access limited (rate limit or access denied)")
                else:
                    print(f"{source['name']} returned HTTP {e.response.status_code}")
            else:
                print(f"{source['name']} connection failed")
            continue
        except Exception as e:
            print(f"Failed to check {source['name']}: {e}")
            continue
        
    print("All update sources failed")
    return None

def download_requirements_from_release():
    """
    Download requirements.txt file directly from the latest release.
    Needed for legacy installation upgrades.
    """
    if os.path.exists("requirements.txt"):
        return True
    
    print("requirements.txt not found. Downloading from latest release...")
    
    # Get latest release info to find the tag
    release_info = get_latest_release_info()
    if not release_info:
        print("Could not get release information")
        return False
    
    tag = release_info["tag_name"]
    source_name = release_info.get("source", "Unknown")
    
    # Build raw URL based on source
    if source_name == "GitHub":
        raw_url = f"https://raw.githubusercontent.com/whiteout-project/bot-dev/refs/tags/{tag}/requirements.txt"
    elif source_name == "GitLab":
        raw_url = f"https://gitlab.whiteout-bot.com/whiteout-project/bot/-/raw/{tag}/requirements.txt"
    else:
        print(f"Unknown source: {source_name}")
        return False
    
    try:
        print(f"Downloading from {source_name}: {raw_url}")
        response = requests.get(raw_url, timeout=30)
        
        if response.status_code == 200:
            with open("requirements.txt", "w") as f:
                f.write(response.text)
            print("Successfully downloaded requirements.txt")
            return True
        else:
            print(f"Failed to download: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error downloading requirements.txt: {e}")
        return False

def check_and_install_requirements():
    """Check each requirement and install missing ones."""
    if not os.path.exists("requirements.txt"):
        return False
        
    with open("requirements.txt", "r") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    print_status(f"{len(requirements)} requirements found", "arrow", indent=1)
    
    missing_packages = []
    
    for requirement in requirements:
        package_name = requirement.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0]
        
        try:
            if package_name == "discord.py":
                import discord
            elif package_name == "aiohttp-socks":
                import aiohttp_socks
            elif package_name == "python-dotenv":
                import dotenv
            elif package_name == "python-bidi":
                import bidi
            elif package_name == "arabic-reshaper":
                import arabic_reshaper
            elif package_name.lower() == "pillow":
                import PIL
            elif package_name.lower() == "numpy":
                import numpy
            elif package_name.lower() == "onnxruntime":
                import onnxruntime
            else:
                __import__(package_name)
                        
        except ImportError:
            missing_packages.append(requirement)
    
    if missing_packages:
        print_status(f"{len(missing_packages)} packages missing", "warning", indent=1)
        print_status("Installing missing packages...", "arrow", indent=1)
        
        for package in missing_packages:
            try:
                cmd = [sys.executable, "-m", "pip", "install", package, "--no-cache-dir"]
                
                subprocess.check_call(cmd, timeout=1200, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print_status(f"Installed {package}", "success", indent=2)
                
            except Exception as e:
                print_status(f"Failed to install {package}: {e}", "error", indent=2)
                return False
    
    print_status("All requirements satisfied", "success", indent=1)
    return True

def setup_dependencies():
    """Main function to set up all dependencies."""
    print("\n" + F.CYAN + "• Checking dependencies..." + R)
    
    if not os.path.exists("requirements.txt"):
        print_status("requirements.txt not found", "warning", indent=1)
        if not download_requirements_from_release():
            print_status("Failed to download requirements.txt", "error", indent=1)
            print_status("Please get the requirements.txt file from the latest release: https://github.com/whiteout-project/bot/releases", "info", indent=1)
            return False

    if not check_and_install_requirements():
        print_status("Failed to install requirements", "error", indent=1)
        return False
    
    return True

if not setup_dependencies():
    print("Dependency setup failed. Please install manually with: pip install -r requirements.txt")
    sys.exit(1)

try:
    from colorama import Fore, Style, init
    import discord
except ImportError as e:
    print(f"Import failed even after dependency setup: {e}")
    print("Please restart the script or install dependencies manually")
    sys.exit(1)

# Colorama shortcuts
F = Fore
R = Style.RESET_ALL

def print_status(message, status="info", indent=0):
    """Print formatted status messages"""
    symbols = {
        "success": (F.GREEN + "✓" + R, F.GREEN),
        "error": (F.RED + "✗" + R, F.RED),
        "warning": (F.YELLOW + "!" + R, F.YELLOW),
        "info": (F.CYAN + "•" + R, F.CYAN),
        "processing": ("...", ""),
        "arrow": ("→", "")
    }
    
    symbol, color = symbols.get(status, ("", ""))
    prefix = "  " * indent + symbol + " " if symbol else "  " * indent
    print(prefix + color + message + R if color else prefix + message)

import warnings

def startup_cleanup():
    """Perform all cleanup tasks on startup - directories, files, and legacy packages."""
    cleanup_performed = False
    
    v1_path = "V1oldbot"
    if os.path.exists(v1_path) and safe_remove(v1_path):
        if not cleanup_performed:
            print_status("System maintenance...", "info")
            cleanup_performed = True
        print_status(f"Removed old directory: {v1_path}", "arrow", indent=1)
    
    v2_path = "V2Old"
    if os.path.exists(v2_path) and safe_remove(v2_path):
        if not cleanup_performed:
            print_status("System maintenance...", "info")
            cleanup_performed = True
        print_status(f"Removed old directory: {v2_path}", "arrow", indent=1)
    
    pictures_path = "pictures"
    if os.path.exists(pictures_path) and safe_remove(pictures_path):
        if not cleanup_performed:
            print_status("System maintenance...", "info")
            cleanup_performed = True
        print_status(f"Removed old directory: {pictures_path}", "arrow", indent=1)
    
    txt_path = "autoupdateinfo.txt"
    if os.path.exists(txt_path) and safe_remove(txt_path):
        if not cleanup_performed:
            print_status("System maintenance...", "info")
            cleanup_performed = True
        print_status(f"Removed old file: {txt_path}", "arrow", indent=1)
    
    removed_count = cleanup_legacy_packages()
    if removed_count > 0 and not cleanup_performed:
        print_status("System maintenance...", "info")

startup_cleanup()

warnings.filterwarnings("ignore", category=DeprecationWarning)

init(autoreset=True)

print("\n" + F.CYAN + "• Initializing bot environment..." + R)
print_status("Core imports successful", "success", indent=1)

try:
    import ssl
    import certifi

    def _create_ssl_context_with_certifi():
        return ssl.create_default_context(cafile=certifi.where())
    
    original_create_default_https_context = getattr(ssl, "_create_default_https_context", None)

    if original_create_default_https_context is None or \
       original_create_default_https_context is ssl.create_default_context:
        ssl._create_default_https_context = _create_ssl_context_with_certifi
        
        print_status("SSL context patched", "success", indent=1)
    else:
        print_status("SSL context already modified", "warning", indent=1)
except ImportError:
    print_status("Certifi library not found", "warning", indent=1)
except Exception as e:
    print_status(f"Error applying SSL context patch: {e}", "error", indent=1)

if __name__ == "__main__":
    import requests

    # Check for mutually exclusive flags
    mutually_exclusive_flags = ["--autoupdate", "--no-update", "--repair"]
    active_flags = [flag for flag in mutually_exclusive_flags if flag in sys.argv]
    
    if len(active_flags) > 1:
        print(F.RED + f"Error: {' and '.join(active_flags)} flags are mutually exclusive." + R)
        print("Use --autoupdate to automatically install updates without prompting.")
        print("Use --no-update to skip all update checks.")
        print("Use --repair to force reinstall/repair missing or corrupted files.")
        sys.exit(1)

    def restart_bot():
        python = sys.executable
        script_path = os.path.abspath(sys.argv[0])
        # Filter out --no-venv and --repair from restart args to avoid loops
        filtered_args = [arg for arg in sys.argv[1:] if arg not in ["--no-venv", "--repair"]]
        args = [python, script_path] + filtered_args

        if sys.platform == "win32":
            # For Windows, provide direct venv command like initial setup
            print(F.YELLOW + "Please restart the bot manually to continue:" + R)
            print(F.CYAN + f"  1. Ensure CMD or PowerShell is open in this directory: {os.getcwd()}" + R)
            
            venv_path = "bot_venv"
            venv_python_name = os.path.join(venv_path, "Scripts", "python.exe")
            print(F.CYAN + "  2. Run this exact command: " + F.GREEN + f"{venv_python_name} {os.path.basename(script_path)}" + R)
            sys.exit(0)
        else:
            # For non-Windows, try automatic restart
            print(F.YELLOW + "Restarting bot..." + R)
            try:
                subprocess.Popen(args)
                os._exit(0)
            except Exception as e:
                print(f"Error restarting: {e}")
                os.execl(python, python, script_path, *sys.argv[1:])
            
    def install_packages(requirements_txt_path: str, debug: bool = False) -> bool:
        """Install packages from requirements.txt file using pip install -r."""
        full_command = [sys.executable, "-m", "pip", "install", "-r", requirements_txt_path, "--no-cache-dir"]
        
        try:
            if debug:
                subprocess.check_call(full_command, timeout=1200)
            else:
                subprocess.check_call(full_command, timeout=1200, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            if debug:
                print(f"Failed to install requirements: {e}")
            return False
    
    async def check_and_update_files():
        beta_mode = "--beta" in sys.argv
        repair_mode = "--repair" in sys.argv
        
        print("\n" + F.CYAN + "• Checking for updates..." + R)
        
        release_info = get_latest_release_info(beta_mode=beta_mode)
        
        if release_info:
            latest_tag = release_info["tag_name"]
            source_name = release_info["source"]
            
            # Check current version
            if repair_mode:
                print_status(f"Repair mode: Forcing reinstall from {latest_tag}", "warning", indent=1)
                current_version = "repair-mode"  # Force update in repair mode
            elif os.path.exists("version"):
                with open("version", "r") as f:
                    current_version = f.read().strip()
                if beta_mode:
                    print_status("Beta mode active", "info", indent=1)
            else:
                current_version = "v0.0.0"
                if beta_mode:
                    print_status("Beta mode active", "info", indent=1)

            if not repair_mode:
                print_status(f"Current version: {current_version}", "arrow", indent=1)
                print_status(f"Latest version: {latest_tag}", "arrow", indent=1)

            if current_version != latest_tag or repair_mode:
                if repair_mode:
                    print_status(f"Repairing installation from {source_name}", "warning", indent=1)
                else:
                    print_status("Update available!", "warning", indent=1)
                    print("\n" + F.CYAN + "Update Notes:" + R)
                    print(release_info["body"])
                print()
                
                update = False
                
                if not is_container():
                    if "--autoupdate" in sys.argv or repair_mode:
                        update = True
                    else:
                        print("Note: If your terminal is not interactive, you can use the --autoupdate argument to skip this prompt.")
                        ask = input("Do you want to update? (y/n): ").strip().lower()
                        update = ask == "y"
                else:
                    print_status("Running in a container. Skipping update prompt.", "info", indent=1)
                    update = True
                    
                if update:
                    # Backup requirements.txt for dependency comparison
                    if os.path.exists("requirements.txt"):
                        try:
                            shutil.copy2("requirements.txt", "requirements.old")
                        except Exception as e:
                            print(F.YELLOW + f"Could not backup requirements.txt: {e}" + R)
                    
                    if os.path.exists("db") and os.path.isdir("db"):
                        print_status("Making backup of database...", "info", indent=1)
                        
                        db_bak_path = "db.bak"
                        if os.path.exists(db_bak_path) and os.path.isdir(db_bak_path):
                            if not safe_remove(db_bak_path): # Create a timestamped backup to avoid upgrading without first having a backup
                                db_bak_path = f"db.bak_{int(datetime.now().timestamp())}"
                                print(F.YELLOW + f"WARNING: Couldn't remove db.bak folder: {e}. Making backup with timestamp instead." + R)

                        try:
                            shutil.copytree("db", db_bak_path)
                            print_status(f"Backup completed: db → {db_bak_path}", "success", indent=2)
                        except Exception as e:
                            print(F.RED + f"WARNING: Failed to create database backup: {e}" + R)
                                            
                    download_url = release_info["download_url"]
                    if not download_url:
                        print(F.RED + "No download URL available for this release" + R)
                        return
                        
                    print_status(f"Downloading update from {source_name}...", "info", indent=1)
                    safe_remove("package.zip")
                    download_resp = requests.get(download_url, timeout=600)
                    
                    if download_resp.status_code == 200:
                        with open("package.zip", "wb") as f:
                            f.write(download_resp.content)
                        
                        if os.path.exists("update") and os.path.isdir("update"):
                            if not safe_remove("update"):
                                print(F.RED + "WARNING: Could not remove previous update directory" + R)
                                return
                            
                        try:
                            shutil.unpack_archive("package.zip", "update", "zip")
                        except Exception as e:
                            print(F.RED + f"ERROR: Failed to extract update package: {e}" + R)
                            return
                            
                        safe_remove("package.zip")
                        
                        # Find the extracted directory (GitHub/GitLab archives create a subdirectory)
                        update_dir = "update"
                        extracted_items = os.listdir(update_dir)
                        if len(extracted_items) == 1 and os.path.isdir(os.path.join(update_dir, extracted_items[0])):
                            update_dir = os.path.join(update_dir, extracted_items[0])
                        
                        # Handle main.py update
                        main_py_path = os.path.join(update_dir, "main.py")
                        if os.path.exists(main_py_path):
                            safe_remove("main.py.bak")
                                
                            try:
                                if os.path.exists("main.py"):
                                    os.rename("main.py", "main.py.bak")
                            except Exception as e:
                                print(F.YELLOW + f"Could not backup main.py: {e}" + R)
                                # If backup fails, just remove the current file
                                if safe_remove("main.py"):
                                    print(F.YELLOW + "Removed current main.py" + R)
                                else:
                                    print(F.RED + "Warning: Could not backup or remove current main.py" + R)
                            
                            try:
                                shutil.copy2(main_py_path, "main.py")
                            except Exception as e:
                                print(F.RED + f"ERROR: Could not install new main.py: {e}" + R)
                                return
                            
                        requirements_path = os.path.join(update_dir, "requirements.txt")
                        if os.path.exists(requirements_path):                      
                            print(F.YELLOW + "Installing any new requirements..." + R)
                            
                            success = install_packages(requirements_path, debug="--verbose" in sys.argv or "--debug" in sys.argv)
                            
                            if success:
                                print(F.GREEN + "New requirements installed." + R)
                                
                                # Copy new requirements.txt to working directory before cleanup
                                try:
                                    if os.path.exists("requirements.txt"):
                                        os.remove("requirements.txt")
                                    shutil.copy2(requirements_path, "requirements.txt")
                                    print(F.GREEN + "Updated requirements.txt" + R)
                                except Exception as e:
                                    print(F.YELLOW + f"Warning: Could not update requirements.txt: {e}" + R)
                                
                                # Now cleanup removed packages (comparing old vs new)
                                cleanup_removed_packages()
                            else:
                                print(F.RED + "Failed to install requirements." + R)
                                return
                            
                            # Remove the requirements.txt from update folder after copying
                            safe_remove(requirements_path)
                            
                        for root, _, files in os.walk(update_dir):
                            for file in files:
                                if file == "main.py":
                                    continue
                                    
                                src_path = os.path.join(root, file)
                                rel_path = os.path.relpath(src_path, update_dir)
                                dst_path = os.path.join(".", rel_path)
                                
                                # Skip certain files that shouldn't be overwritten
                                if file in ["bot_token.txt", "version"] or dst_path.startswith("db/") or dst_path.startswith("db\\"):
                                    continue
                                
                                os.makedirs(os.path.dirname(dst_path), exist_ok=True)

                                # Only backup cogs Python files (.py extension)
                                norm_path = dst_path.replace("\\", "/")
                                is_cogs_file = (norm_path.startswith("cogs/") or norm_path.startswith("./cogs/")) and file.endswith(".py")
                                
                                if is_cogs_file and os.path.exists(dst_path):
                                    # Calculate file hashes to check if backup is needed
                                    src_hash = calculate_file_hash(src_path)
                                    dst_hash = calculate_file_hash(dst_path)
                                    
                                    if src_hash != dst_hash:
                                        # Files are different, create backup
                                        cogs_bak_dir = "cogs.bak"
                                        os.makedirs(cogs_bak_dir, exist_ok=True)
                                        
                                        # Get relative path within cogs directory
                                        rel_path_in_cogs = os.path.relpath(dst_path, "cogs")
                                        backup_path = os.path.join(cogs_bak_dir, rel_path_in_cogs)
                                        
                                        # Create subdirectories in backup if needed
                                        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                                        
                                        try:
                                            # Remove old backup if exists
                                            if os.path.exists(backup_path):
                                                os.remove(backup_path)
                                            # Copy current file to backup
                                            shutil.copy2(dst_path, backup_path)
                                        except Exception as e:
                                            print(F.YELLOW + f"Could not create backup of {dst_path}: {e}" + R)
                                        
                                try:
                                    shutil.copy2(src_path, dst_path)
                                except Exception as e:
                                    print(F.RED + f"Failed to copy {file} to {dst_path}: {e}" + R)
                        
                        if not safe_remove("update"):
                            print(F.RED + "WARNING: update folder could not be removed. You may want to remove it manually." + R)
                        
                        with open("version", "w") as f:
                            f.write(latest_tag)
                        
                        print_status(f"Update completed successfully from {source_name}", "success", indent=1)
                        
                        restart_bot()
                    else:
                        print(F.RED + f"Failed to download the update from {source_name}. HTTP status: {download_resp.status_code}" + R)
                        return
            else:
                print_status("Bot is up to date", "success", indent=1)
        else:
            print_status("Failed to fetch latest release info from all sources", "error", indent=1)
        
    import asyncio
    from datetime import datetime
            
    # Handle update/repair logic
    if "--repair" in sys.argv:
        asyncio.run(check_and_update_files())
    elif "--no-update" in sys.argv:
        print("\n" + F.CYAN + "• Checking for updates..." + R)
        print_status("Update check skipped (--no-update flag)", "info", indent=1)
    else:
        asyncio.run(check_and_update_files())
            
    import discord
    from discord.ext import commands
    import sqlite3

    class CustomBot(commands.Bot):
        async def on_error(self, event_name, *args, **kwargs):
            if event_name == "on_interaction":
                error = sys.exc_info()[1]
                if isinstance(error, discord.NotFound) and error.code == 10062:
                    return
            
            await super().on_error(event_name, *args, **kwargs)

        async def on_command_error(self, ctx, error):
            if isinstance(error, discord.NotFound) and error.code == 10062:
                return
            await super().on_command_error(ctx, error)

    intents = discord.Intents.default()
    intents.message_content = True

    bot = CustomBot(command_prefix="/", intents=intents)

    init(autoreset=True)

    token_file = "bot_token.txt"
    if not os.path.exists(token_file):
        bot_token = input("Enter the bot token: ")
        with open(token_file, "w") as f:
            f.write(bot_token)
    else:
        with open(token_file, "r") as f:
            bot_token = f.read().strip()

    if not os.path.exists("db"):
        os.makedirs("db")

    databases = {
        "conn_alliance": "db/alliance.sqlite",
        "conn_giftcode": "db/giftcode.sqlite",
        "conn_changes": "db/changes.sqlite",
        "conn_users": "db/users.sqlite",
        "conn_settings": "db/settings.sqlite",
    }

    connections = {name: sqlite3.connect(path) for name, path in databases.items()}
    
    print("\n" + F.CYAN + "• Initializing database..." + R)
    print_status("Database connections established", "success", indent=1)

    def create_tables():
        with connections["conn_changes"] as conn_changes:
            conn_changes.execute("""CREATE TABLE IF NOT EXISTS nickname_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                fid INTEGER, 
                old_nickname TEXT, 
                new_nickname TEXT, 
                change_date TEXT
            )""")
            
            conn_changes.execute("""CREATE TABLE IF NOT EXISTS furnace_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                fid INTEGER, 
                old_furnace_lv INTEGER, 
                new_furnace_lv INTEGER, 
                change_date TEXT
            )""")

        with connections["conn_settings"] as conn_settings:
            conn_settings.execute("""CREATE TABLE IF NOT EXISTS botsettings (
                id INTEGER PRIMARY KEY, 
                channelid INTEGER, 
                giftcodestatus TEXT 
            )""")
            
            conn_settings.execute("""CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY, 
                is_initial INTEGER
            )""")

        with connections["conn_users"] as conn_users:
            conn_users.execute("""CREATE TABLE IF NOT EXISTS users (
                fid INTEGER PRIMARY KEY, 
                nickname TEXT, 
                furnace_lv INTEGER DEFAULT 0, 
                kid INTEGER, 
                stove_lv_content TEXT, 
                alliance TEXT
            )""")

        with connections["conn_giftcode"] as conn_giftcode:
            conn_giftcode.execute("""CREATE TABLE IF NOT EXISTS gift_codes (
                giftcode TEXT PRIMARY KEY, 
                date TEXT
            )""")
            
            conn_giftcode.execute("""CREATE TABLE IF NOT EXISTS user_giftcodes (
                fid INTEGER, 
                giftcode TEXT, 
                status TEXT, 
                PRIMARY KEY (fid, giftcode),
                FOREIGN KEY (giftcode) REFERENCES gift_codes (giftcode)
            )""")

        with connections["conn_alliance"] as conn_alliance:
            conn_alliance.execute("""CREATE TABLE IF NOT EXISTS alliancesettings (
                alliance_id INTEGER PRIMARY KEY, 
                channel_id INTEGER, 
                interval INTEGER
            )""")
            
            conn_alliance.execute("""CREATE TABLE IF NOT EXISTS alliance_list (
                alliance_id INTEGER PRIMARY KEY, 
                name TEXT
            )""")

        print_status("All tables verified", "success", indent=1)

    create_tables()

    async def load_cogs():
        cogs = ["olddb", "control", "alliance", "alliance_member_operations", "bot_operations", "logsystem", "support_operations", "gift_operations", "changes", "w", "wel", "other_features", "bear_trap", "id_channel", "backup_operations", "bear_trap_editor", "attendance", "attendance_report", "minister_schedule", "minister_menu"]
        
        print("\n" + F.CYAN + "• Loading extensions..." + R)
        
        failed_cogs = []
        loaded_cogs = []
        
        for cog in cogs:
            try:
                await bot.load_extension(f"cogs.{cog}")
                loaded_cogs.append(cog)
            except Exception as e:
                failed_cogs.append((cog, str(e)))
        
        # Show successful loads in a compact way
        if loaded_cogs:
            print_status(f"{len(loaded_cogs)} extensions loaded successfully", "success", indent=1)
        
        # Show failures with details
        if failed_cogs:
            print_status(f"{len(failed_cogs)} extension(s) failed to load:", "error", indent=1)
            for cog, error in failed_cogs:
                print_status(f"{cog}: {error[:60]}...", "arrow", indent=2)
            print()
            print_status("Bot will continue with reduced functionality", "warning", indent=1)
            print_status("To fix missing or corrupted files, run: python main.py --repair", "info", indent=1)

    @bot.event
    async def on_ready():
        try:
            print("\n" + F.GREEN + "✓ Bot initialized successfully" + R)
            print_status(f"Logged in as: {bot.user}", "info")
            await bot.tree.sync()
        except Exception as e:
            print_status(f"Error syncing commands: {e}", "error")

    async def main():
        await load_cogs()
        
        await bot.start(bot_token)

    if __name__ == "__main__":
        asyncio.run(main())