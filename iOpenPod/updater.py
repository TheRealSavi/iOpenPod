import os
import subprocess
import logging

logger = logging.getLogger(__name__)

def update_iOpenPod(update_file):
    try:
        # Ensure the update file has the correct permissions
        os.chmod(update_file, 0o755)
        # Run the update installer
        subprocess.run([update_file], check=True)
        logger.info('Update installed successfully')
    except Exception as e:
        logger.error(f'Failed to install update: {e}')

def restart_iOpenPod():
    try:
        # Properly shut down the app before restarting
        subprocess.run(['pkill', '-f', 'iOpenPod'], check=True)
        # Restart the app
        subprocess.run(['iOpenPod'], check=True)
        logger.info('iOpenPod restarted successfully')
    except Exception as e:
        logger.error(f'Failed to restart iOpenPod: {e}')