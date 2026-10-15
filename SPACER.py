"""Run SPACER as a standalone desktop application: python SPACER.py [image]."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'gaia_flythrough'))
from version import VERSION


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version=f'SPACER {VERSION}')
    parser.add_argument('image',nargs='?',help='Already-stretched FITS, TIFF, PNG or JPEG; solve unsolved input in the app')
    parser.add_argument('--wcs',help='Solved FITS with the same framing as a TIFF/PNG')
    parser.add_argument('--project',help='Open an existing SPACER project')
    args=parser.parse_args()
    if args.image and args.project: parser.error('Choose an image or --project, not both.')
    if args.wcs and not args.image: parser.error('--wcs requires an image.')
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from app import FlythroughWindow
    application=QApplication.instance() or QApplication([sys.argv[0]])
    window=FlythroughWindow()
    try:
        if args.image: window.use_image(args.image,args.wcs)
        elif args.project: window.use_prepared(Path(args.project))
    except Exception as exc:
        QMessageBox.warning(window,'Cannot open input',str(exc))
    window.show()
    return application.exec()


if __name__=='__main__': sys.exit(main())
