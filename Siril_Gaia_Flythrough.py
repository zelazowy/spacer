"""Launch SPACER with the current Siril image as its source."""
import sys
from pathlib import Path
import traceback
import sirilpy as s
s.ensure_installed('numpy','scipy','astropy','Pillow','tifffile','PyQt6')
sys.path.insert(0,str(Path(__file__).resolve().parent/'gaia_flythrough'))
from app import FlythroughWindow
from PyQt6.QtWidgets import QApplication, QMessageBox


def main():
    app=QApplication.instance() or QApplication(sys.argv)
    siril=s.SirilInterface()
    try:
        siril.connect()
        window=FlythroughWindow(siril);window.show();app.exec()
    except Exception as exc:
        traceback.print_exc();QMessageBox.critical(None,'SPACER',str(exc))
    finally:
        if siril.connected: siril.disconnect()


if __name__=='__main__': main()
