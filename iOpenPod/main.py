import logging
from app_core.bootstrap import main, run_pyqt_app
from .updater import update_iOpenPod, restart_iOpenPod

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.error(f'Failed to start iOpenPod: {e}')
        # Check if an update is available and install it if necessary
        update_iOpenPod('path/to/update/file')
        # Restart the app after installing the update
        restart_iOpenPod()