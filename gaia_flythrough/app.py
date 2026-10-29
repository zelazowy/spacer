"""Shared SPACER desktop interface; Siril is an optional image source."""
import sys
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import threading
import traceback

from motion import validate_motion
from ui_units import ZoomSpinBox
from version import VERSION, field_description
from preferences import Preferences
from photo_date import infer_photo_date, date_info
from siril_pipeline import normalized_pixels, parse_header, has_solution, find_tool, run_pipeline, render_prepared, load_prepared_scene, read_project, resume_project, calculation_folder, recalculation_missing, recalculate_project, UNSOLVED_MESSAGE
from astropy.time import Time
from image_source import FileImageSource
from astap_solver import solve_project, find_astap, resolve_astap
from astro_platesolve import SolveOptions, validate_backend
from task_progress import Diagnostic
from density import DEFAULT_MAX_STARS, MAX_MOVING_STARS
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,
    QLabel,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPushButton,QFileDialog,
    QMessageBox,QPlainTextEdit,QGroupBox,QToolButton,QProgressBar,QSizePolicy,QDialog,QDialogButtonBox,QScrollArea,QCheckBox)




class TargetWorker(QThread):
    completed=pyqtSignal(object)
    failed=pyqtSignal(str)
    def __init__(self,header):
        super().__init__();self.header=header
    def run(self):
        try:
            from targets import find_targets
            self.completed.emit(find_targets(self.header))
        except Exception as exc:self.failed.emit(str(exc))


class Worker(QThread):
    progress=pyqtSignal(str,bool)
    frame_progress=pyqtSignal(int,int,float)
    stage_progress=pyqtSignal(str,int,int,float)
    completed=pyqtSignal(str)
    failed=pyqtSignal(str)
    def __init__(self,pixels,header,options):
        super().__init__()
        self.pixels,self.header,self.options=pixels,header,options
        self.cancel=threading.Event()
        self.options.frame_progress=self.frame_progress.emit
        self.options.stage_progress=self.stage_progress.emit
    def report(self,message):
        detail=getattr(message,'detail',False)
        if not detail:
            print(f'[{datetime.now():%H:%M:%S}] {message}',flush=True)
        self.progress.emit(str(message),detail)

    def run(self):
        try:
            self.report('Project folder: '+str(self.options.output))
            if getattr(self.options,'solve',False):
                out=solve_project(self.options,self.report,self.cancel)
            elif getattr(self.options,'recalculate',False):
                out=recalculate_project(self.options.output,self.options,self.report,self.cancel)
            elif getattr(self.options,'reuse',False):
                out=resume_project(self.options.output,self.options,self.report,self.cancel)
            else:
                out=run_pipeline(self.pixels,self.header,self.options,self.report,self.cancel)
            self.completed.emit(str(out))
        except Exception as exc:
            self.report(str(exc))
            self.report(Diagnostic(traceback.format_exc()))
            self.failed.emit(str(exc))


class FlythroughWindow(QWidget):
    def __init__(self,siril=None):
        super().__init__()
        self.siril=siril;self.file_source=None;self.worker=None;self.result=None;self.prepared=None;self.result_stem=None
        self.preferences=Preferences()
        self.auto_date_info=None
        self.target_worker=None;self.target_info=None
        self.prepared_star_limit=None;self.prepared_star_count=None;self.prepared_approximate=None
        self.render_succeeded=False
        self.setWindowTitle(f'SPACER — v{VERSION}')
        from workspace_ui import Workspace
        self.workflow=Workspace(self)
        self.append_log('Ready. Tool setup is shared across projects. Original source images are preserved.')
        self.refresh_motion_ui();self.refresh_project()
        if self.siril:self.detect_siril_date()
        if self.image_filename() and Path(self.output.text()).is_dir() and any(Path(self.output.text()).iterdir()):
            try:self.use_prepared(Path(self.output.text()))
            except (ValueError,OSError) as exc:self.status.setText(str(exc))

    def image_filename(self):
        if self.siril: return self.siril.get_image_filename()
        return str(self.file_source.path) if self.file_source else None

    def open_image(self):
        selected,_=QFileDialog.getOpenFileName(self,'Open a finished image',self.preferences.directory('image_directory'),filter='Images (*.fits *.fit *.fts *.tif *.tiff *.png *.jpg *.jpeg)')
        if not selected: return
        try: self.use_image(selected)
        except Exception as exc: self.show_problem('Cannot open image',str(exc))

    def open_coordinates(self):
        if not self.file_source: return
        selected,_=QFileDialog.getOpenFileName(self,'Sky coordinates — select a solved FITS of this same image',self.preferences.directory('reference_directory'),filter='Solved FITS (*.fits *.fit *.fts)')
        if not selected: return
        try:
            candidate=FileImageSource(self.file_source.path,selected)
            candidate.snapshot()  # Validate dimensions and pixels before accepting the reference.
            self.file_source=candidate;self.set_date_info(candidate.date_info());self.remember_image();self.preferences.save(reference_directory=str(Path(selected).resolve().parent));self.refresh_project()
        except Exception as exc:
            self.status.setText(str(exc))
            QMessageBox.warning(self,'Cannot use sky coordinates',str(exc))

    def use_image(self,path,wcs_path=None):
        source=FileImageSource(path,wcs_path)
        # Validate the header before changing the selected project.
        if source.has_coordinates: source.header()
        self.file_source=source;self.prepared=None;self.reset_target_distance();self.target.clear();self.set_date_info(source.date_info())
        self.star_limit.setValue(DEFAULT_MAX_STARS)
        self.approximate_distances.setChecked(False)
        self.prepared_star_limit=None;self.prepared_star_count=None;self.prepared_approximate=None
        self.output.setText(str(source.path.parent/'flythrough'/source.path.stem))
        self.refresh_project()
        self.remember_image()
        self.workflow.go(0)
        if Path(self.output.text()).is_dir() and any(Path(self.output.text()).iterdir()): self.use_prepared(Path(self.output.text()))

    def refresh_motion_ui(self,*_):
        physical=self.zoom_mode.currentData()=='target_distance'
        self.flight_form.setRowVisible(self.zoom,not physical)
        self.zoom.setEnabled(not physical)
        self.flight_form.setRowVisible(self.target_row,physical)
        self.flight_form.setRowVisible(self.perspective_note,physical)
        self.target_distance_pc.setEnabled(physical)
        self.motion_settings_toggle.setVisible(physical)
        self.motion_settings.setVisible(physical and self.motion_settings_toggle.isChecked())
        d,s=self.target_distance_pc.value(),self.travel_pc.value()
        from ui_units import distance_label as approximate_distance_label
        if d:
            name=self.target_info['name'] if self.target_info else 'Manual distance'
            self.target_summary.setText(f'{name} · {approximate_distance_label(d)}')
        else:self.target_summary.setText('No target selected')
        self.target_summary.setToolTip(self.target_origin.text())
        self.perspective_note.setText('Choose a catalogue target or enter a distance.' if not d else (
            ('Very little background zoom at this distance.' if d/(d-s)<1.005 else f'Final enlargement: {d/(d-s):.3g}×') if d>s else 'Reduce travel distance; it must be less than the target distance.'))
        if hasattr(self,'start'):
            if hasattr(self,'workflow'):self.workflow.refresh()

    def reset_target_distance(self):
        self.target_distance_pc.setValue(0)
        self.clear_target_origin()
        self.target_origin.setText('No target distance selected for this image')

    def clear_target_origin(self,*_):
        self.target_info=None
        self.target_origin.setText('Manual target distance')
        self.refresh_motion_ui()

    def target_header(self):
        from astropy.io import fits
        if self.prepared and (self.prepared/'source_wcs.fits').exists():
            return fits.getheader(self.prepared/'source_wcs.fits')
        if self.siril:return parse_header(self.siril.get_image_fits_header())
        if self.file_source:return self.file_source.header()
        raise ValueError('Open a plate-solved image or saved project first.')

    def lookup_targets(self):
        try:
            if self.worker and self.worker.isRunning():raise ValueError('Wait for processing to finish.')
            header=self.target_header()
            from targets import field_query
            query,*_=field_query(header)
            self.target_lookup_query=query
            self.target_worker=TargetWorker(header)
            self.find_targets_button.setEnabled(False);self.find_targets_button.setText('Looking up SIMBAD…')
            self.target_worker.completed.connect(self.show_targets)
            self.target_worker.failed.connect(lambda message:self.show_problem('Target lookup failed',message))
            self.target_worker.finished.connect(self.target_lookup_finished)
            self.target_worker.start()
        except Exception as exc:self.show_problem('Cannot find targets',str(exc))

    def target_lookup_finished(self):
        self.find_targets_button.setText('Choose target…');self.find_targets_button.setEnabled(True)

    def show_targets(self,rows):
        from targets import field_query
        try:
            if field_query(self.target_header())[0]!=self.target_lookup_query:
                self.show_problem('Field changed','The image changed during lookup. Find targets again.');return
        except Exception:return
        if not rows:
            self.show_problem('No catalogue targets','No familiar deep-sky catalogue targets were found in this frame. You can enter a distance manually.');return
        from targets import approximate_targets
        from ui_units import distance_label as approximate_distance_label
        rows=approximate_targets(rows)
        dialog=QDialog(self);dialog.setWindowTitle('Choose a target')
        layout=QVBoxLayout(dialog)
        note=QLabel('Choose the object you want to travel toward.')
        note.setWordWrap(True);layout.addWidget(note)
        choice=QComboBox()
        for row in rows:
            distance=approximate_distance_label(row['distance_pc'])
            choice.addItem(f"{row['name']} · {distance}",row)
        layout.addWidget(choice)
        details=QLabel();details.setWordWrap(True);layout.addWidget(details)
        def update_details():
            row=choice.currentData()
            details.setText('Approximate distance. You can adjust it in the Target distance field.' if row['distance_pc'] else 'No distance available. Enter one in the Target distance field.')
            details.setToolTip(row['distance_summary'])
        choice.currentIndexChanged.connect(update_details);update_details()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.resize(680,260)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        row=choice.currentData()
        if row['distance_pc'] is None:
            self.reset_target_distance();self.target_origin.setText(row['name']+': no published distance here; enter manually.');return
        if not self.target_distance_pc.minimum()<=row['distance_pc']<=self.target_distance_pc.maximum():
            self.show_problem('Distance outside supported range','Enter a target distance within the supported range manually.');return
        self.target_distance_pc.setValue(row['distance_pc'])
        self.target_info=dict(row,selected_at=datetime.now().astimezone().isoformat())
        self.target_origin.setText(f"{row['name']} · approximate SIMBAD distance")
        self.zoom_mode.setCurrentIndex(self.zoom_mode.findData('target_distance'))
        self.refresh_motion_ui()

    def set_date_info(self,info):
        self.auto_date_info=info
        self.epoch.setText(info['value'].split('T')[0] if info else '')
        self.update_date_origin()

    def selected_date_info(self):
        text=self.epoch.text().strip()
        if self.auto_date_info and text in (self.auto_date_info['value'],self.auto_date_info['value'].split('T')[0]): return dict(self.auto_date_info)
        return date_info(text,'Manual date') if text else None

    def update_date_origin(self,*_):
        info=self.selected_date_info()
        if info:
            prefix='Estimated from ' if info['approximate'] else 'From '
            suffix=' You can override it.' if self.preparation.isEnabled() else ' Saved matching date.'
            self.date_origin.setText(prefix+info['source']+'.'+suffix)
        else: self.date_origin.setText('No usable date found. Enter an approximate capture year.' if self.preparation.isEnabled() else 'Saved matching date is not recorded.')

    def detect_siril_date(self):
        try:
            header=parse_header(self.siril.get_image_fits_header(),require_solution=False)
            self.set_date_info(infer_photo_date(self.image_filename() or '',header))
        except (AttributeError,ValueError,OSError): pass

    def remember_image(self):
        if self.siril or not self.file_source: return
        self.preferences.save(last_kind='image',last_image=str(self.file_source.path),
            last_wcs=str(self.file_source.wcs_path) if self.file_source.wcs_path else '',
            image_directory=str(self.file_source.path.parent))

    def remember_project(self,folder):
        folder=Path(folder).expanduser().resolve()
        self.preferences.save(last_kind='project',last_project=str(folder),project_directory=str(folder.parent))

    def restore_last(self):
        """Standalone startup only; never replace Siril input or explicit CLI arguments."""
        if self.siril: return
        state=self.preferences.data
        try:
            if state.get('last_kind')=='project':
                folder=state.get('last_project','')
                if not isinstance(folder,str) or not folder or not Path(folder).is_dir(): return
                self.use_prepared(Path(folder))
            elif state.get('last_kind')=='image':
                path=state.get('last_image','')
                if not isinstance(path,str) or not path or not Path(path).is_file(): return
                wcs=state.get('last_wcs','')
                wcs=wcs if isinstance(wcs,str) and wcs and Path(wcs).is_file() else None
                self.use_image(path,wcs)
        except (ValueError,OSError,TypeError) as exc:
            self.append_log('Could not reopen the last input: '+str(exc))

    def solve_image(self):
        try:
            if not self.file_source: raise ValueError('Open an image first.')
            validate_backend(SolveOptions(executable=self.astap.text()))
            if not self.output.text().strip(): raise ValueError('Choose a new project folder.')
            info=self.selected_date_info()
            if self.epoch.text().strip() and not info: raise ValueError('Enter a valid capture year or date.')
            if not info: info=self.file_source.date_info()
            date=info['value'] if info else ''
            options=SimpleNamespace(solve=True,output=self.output.text(),source=str(self.file_source.path),
                wcs_path=str(self.file_source.wcs_path) if self.file_source.wcs_path else None,
                astap=self.astap.text(),database=self.database.text().strip(),target=self.target.text().strip(),
                fov=self.fov.value(),radius=self.radius.value(),binning=self.binning.value(),epoch=str(date),date_info=info,
                seconds=self.seconds.value(),zoom=self.zoom_percent(),max_stars=self.star_limit.value(),ffmpeg=self.ffmpeg.text(),
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',executable=self.executable.text())
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot solve sky position',str(exc))

    def zoom_percent(self):
        # Keep the existing project/export contract while presenting direct scale.
        return round((self.zoom.value()-1)*100,1)

    def refresh_project(self):
        folder=Path(self.output.text()).expanduser().resolve()
        saved=any((folder/name).is_file() for name in ('project.json','scene.json','scene_iterative.json','preview.html'))
        self.project_title.setText(folder.name if saved else Path(self.image_filename() or ('Unsaved image' if self.siril else 'No image selected')).name)
        self.project_title.setToolTip(str(folder))
        calculation_error=None
        try: ready=(calculation_folder(folder)/'scene_iterative.json').is_file()
        except ValueError as exc: ready=False;calculation_error=str(exc)
        new_hint=('Uses the current Siril image.' if self.siril else
            ('Ready to prepare.' if self.file_source else 'Use a finished, stretched image.'))
        self.project_hint.setText('Uses the saved project image.' if saved else new_hint)
        self.project_hint.setToolTip(str(folder))
        self.preparation.setEnabled(not saved or read_project(folder).get('stage')=='solved')
        self.update_date_origin()
        self.preparation_note.setText(self.new_preparation_note if not saved or read_project(folder).get('stage')=='solved' else
            'Uses the saved image and preparation settings. Completed star-removal output is reused.\nChanging an engine path does not change saved starless layers or prepared stars.')
        self.update_calculation_hint()
        if folder!=self.prepared:
            self.render_succeeded=False;self.progress_bar.hide();self.render_counter.hide()
            self.result=None;self.result_stem=None
            self.preview.setEnabled(False);self.video.setEnabled(False)
        self.status.setText(('Ready to render from the saved project.' if ready else 'Ready to resume preparation.') if saved else ('Ready to prepare this image.' if self.siril or self.file_source else 'Open an image or project to begin.'))
        file_selected=bool(not self.siril and self.file_source and not saved)
        missing=bool(file_selected and not self.file_source.has_coordinates)
        embedded=bool(file_selected and self.file_source.has_coordinates and self.file_source.wcs_path is None)
        self.coordinates.setVisible(missing)
        self.solver_settings.setVisible(missing)
        self.solve_button.setEnabled(missing)
        if embedded:
            kind='FITS' if self.file_source.is_fits else ('JPEG EXIF' if self.file_source.path.suffix.lower() in {'.jpg','.jpeg'} else 'Astro-TIFF')
            self.project_hint.setText('Sky position available.')
            self.project_hint.setToolTip(kind+' · sky coordinates and available observation date read from the image.\n'+str(folder))
        if missing:
            self.coordinates_hint.setText('Sky position is not saved in this image.\nSolve it with ASTAP to prepare your flight.')
            self.status.setText('Solve sky position above. ASTAP paths are in Tool setup; solver options are here.')
        self.start.setEnabled((saved or bool(self.siril or self.file_source)) and not missing)
        if calculation_error:
            self.project_hint.setText('Saved image · star calculations need rebuilding.')
            self.status.setText(calculation_error);self.start.setEnabled(False)
        self.preview.setEnabled(ready or bool(self.result and self.result_stem and (self.result/(self.result_stem+'.html')).is_file()))
        if hasattr(self,'workflow'):self.workflow.refresh()

    def update_calculation_hint(self,*_):
        if not hasattr(self,'output'): return
        folder=Path(self.output.text()).expanduser().resolve()
        missing=recalculation_missing(folder)
        self.recalculate_button.setEnabled(not missing)
        saved=any((folder/name).is_file() for name in ('project.json','scene.json','scene_iterative.json','preview.html'))
        if not saved and missing:
            self.calculation_hint.setText('Available after first preparation. Recalculate stars reuses the saved image, starless layer and Gaia catalogue.')
        elif missing:
            self.calculation_hint.setText('Recalculation needs saved layers: '+', '.join(missing)+'.')
        else:
            summary=('Distance coverage changed; recalculate to apply it. ' if self.prepared_approximate is not None and self.approximate_distances.isChecked()!=self.prepared_approximate else '')
            summary+=(f'Prepared: {self.prepared_star_count:,} moving stars. ' if folder==self.prepared and self.prepared_star_count is not None else '')
            if folder==self.prepared and self.prepared_star_limit is not None and self.star_limit.value()>self.prepared_star_limit:
                summary+='Recalculate to apply the higher limit. '
            self.calculation_hint.setText(summary+'Reuses saved layers and catalogue caches. Keeps previous calculations and exports.')
        if hasattr(self,'workflow'):self.workflow.refresh()

    def recalculate_stars(self):
        try:
            folder=Path(self.output.text()).expanduser().resolve()
            missing=recalculation_missing(folder)
            if missing: raise ValueError('Recalculation needs saved project files: '+', '.join(missing))
            options=SimpleNamespace(output=str(folder),recalculate=True,max_stars=self.star_limit.value(),approximate_distances=self.approximate_distances.isChecked())
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot recalculate stars',str(exc))

    def new_from_siril(self):
        name=Path(self.image_filename() or 'image').stem
        dialog=QFileDialog(self,'New project folder',str(Path(self.output.text()).parent))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite,True)
        dialog.setLabelText(QFileDialog.DialogLabel.Accept,'Use folder')
        dialog.selectFile(name+'_project')
        if not dialog.exec(): return
        selected=dialog.selectedFiles()[0]
        folder=Path(selected)
        if folder.exists():
            QMessageBox.information(self,'Choose a new folder','Choose a folder name that does not exist yet. Use Open project to return to an existing project.')
            return
        self.prepared=None;self.reset_target_distance();self.output.setText(str(folder));self.refresh_project();self.detect_siril_date()
        self.star_limit.setValue(DEFAULT_MAX_STARS)
        self.approximate_distances.setChecked(False)
        self.prepared_star_limit=None;self.prepared_star_count=None;self.prepared_approximate=None
        self.workflow.go(0)

    def append_log(self,message,detail=False):
        # Capture full diagnostics even while Details is collapsed.
        self.log.appendPlainText(f'[{datetime.now():%H:%M:%S}] {message}')

    def report_progress(self,message,detail=False):
        self.append_log(message,detail)
        if not detail:
            self.status.setToolTip(message)
            self.status.setText(message if len(message)<160 else message[:157]+'…')

    @staticmethod
    def elapsed_text(seconds):
        seconds=max(0,int(seconds));minutes,seconds=divmod(seconds,60)
        hours,minutes=divmod(minutes,60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

    def show_stage_progress(self,label,done,total,elapsed):
        if self.worker and self.worker.cancel.is_set(): return
        self.status.setText(label+'…');self.status.setToolTip(label)
        self.progress_bar.show()
        if total<0:
            self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
            self.render_counter.clear();self.render_counter.hide();return
        done=max(0,min(done,total))
        self.progress_bar.setRange(0,1000)
        self.progress_bar.setValue(1000 if total==0 else done*1000//total)
        self.progress_bar.setTextVisible(True)
        self.render_counter.setText(self.progress_counter(done,total,elapsed))
        self.render_counter.show()

    def progress_counter(self,done,total,elapsed,prefix=''):
        counter=f'{prefix}{done:,} / {total:,} · elapsed {self.elapsed_text(elapsed)}'
        if done>0 and done<total and elapsed>=2:
            counter+=f' · about {self.elapsed_text(math.ceil(elapsed*(total-done)/done))} remaining'
        return counter

    def show_frame_progress(self,done,total,elapsed):
        if total<=0: return
        self.progress_bar.setRange(0,1000)
        # Frame submission can finish before FFmpeg flushes its output.
        self.progress_bar.setValue(min(999,done*1000//total))
        self.progress_bar.setTextVisible(True);self.progress_bar.show()
        self.render_counter.setText(self.progress_counter(done,total,elapsed,'Frames '));self.render_counter.show()
        if not self.worker or not self.worker.cancel.is_set():
            self.status.setText('Finalizing MP4…' if done==total else 'Rendering video…')

    def show_problem(self,title,message):
        self.status.setText(message)
        QMessageBox.warning(self,title,message)

    def path_row(self,field,directory):
        host=QWidget();host.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        row=QHBoxLayout(host);row.setContentsMargins(0,0,0,0)
        host.setFocusProxy(field)
        field.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        row.addWidget(field,1);button=QPushButton('Browse…')
        button.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed);row.addWidget(button)
        def browse():
            if directory:
                selected=QFileDialog.getExistingDirectory(self,'Choose a project folder',self.picker_directory(field.text()))
                if selected:
                    folder=Path(selected)
                    if any((folder/name).is_file() for name in ('project.json','scene.json','preview.html','scene_iterative.json')):
                        try: self.use_prepared(folder)
                        except Exception as exc: QMessageBox.warning(self,'Prepared field missing',str(exc))
                    else:
                        field.setText(str(folder));self.refresh_project()
            else:
                selected,_=QFileDialog.getOpenFileName(self,'Choose executable',self.picker_directory(field.text()))
                if selected: field.setText(selected)
        button.clicked.connect(browse)
        return host

    def picker_directory(self,value):
        """Start at the current path, or its nearest existing parent."""
        if value.strip():
            path=Path(value).expanduser().resolve()
            while not path.is_dir() and path!=path.parent: path=path.parent
            return str(path)
        source=self.image_filename()
        if source: return str(Path(source).expanduser().resolve().parent)
        return self.preferences.directory('project_directory')
    def choose_engine(self,*_):
        self.executable.setText(find_tool('rc-astro' if self.engine.currentIndex()==0 else 'starnet2'))
    def begin(self):
        try:
            import os
            if not self.output.text().strip(): raise ValueError('Choose a project folder in Prepare image.')
            out=Path(self.output.text()).expanduser()
            if out.exists() and any(out.iterdir()):
                self.use_prepared(out,restore=False)
                self.render_variant()
                return
            checks=[('Star-removal',self.executable)]
            if self.workflow.action=='render':checks.append(('FFmpeg',self.ffmpeg))
            for label,field in checks:
                if not Path(field.text()).is_file() or not os.access(field.text(),os.X_OK):
                    self.workflow.go(4);self.workflow.select_tool(0 if field is self.executable else 2);field.setFocus()
                    raise ValueError(f'{label} executable is missing or not executable. Choose its installed CLI.')
            if self.siril:
                with self.siril.image_lock():
                    source=self.image_filename() or 'unsaved'
                    header=parse_header(self.siril.get_image_fits_header(),require_solution=False)
                    pixels=self.siril.get_image_pixeldata(preview=self.stretch.currentIndex()==1,linked=True)
                    if pixels is None: raise ValueError('No image is loaded.')
                    pixels=normalized_pixels(pixels).copy()
            else:
                if not self.file_source: raise ValueError('Open an image or project first.')
                source=str(self.file_source.path)
                pixels,header=self.file_source.snapshot()
            if not has_solution(header):
                raise ValueError(UNSOLVED_MESSAGE)
            info=self.selected_date_info()
            if self.epoch.text().strip() and not info: raise ValueError('Enter a valid capture year or date.')
            if not info: info=infer_photo_date(source,header)
            date=info['value'] if info else None
            if not date:
                self.workflow.go(0);self.epoch.setFocus()
                raise ValueError('Enter the observation date in Prepare image; this image has no DATE-OBS.')
            Time(date)
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),zoom_mode=self.zoom_mode.currentData(),travel_pc=self.travel_pc.value(),target_distance_pc=self.target_distance_pc.value(),target_info=self.target_info,approximate_distances=self.approximate_distances.isChecked(),max_stars=self.star_limit.value(),mode="iterative",
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=str(Path(self.executable.text()).resolve()),ffmpeg=str(Path(self.ffmpeg.text()).resolve()),layers_only=self.workflow.action=='layers',prepare_only=self.workflow.action=='calculate',fps=self.workflow.fps.currentData(),video_width=self.workflow.resolution.currentData(),
                epoch=str(date),date_info=info,output=str(out),source=source)
            self.launch(pixels,header,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def launch(self,pixels,header,options):
            if not any(getattr(options,name,False) for name in ('solve','recalculate','layers_only','prepare_only')):
                validate_motion(getattr(options,'zoom_mode','independent'),getattr(options,'travel_pc',80),getattr(options,'target_distance_pc',400))
            if hasattr(self.workflow,'pending_step'):del self.workflow.pending_step
            self.prepared=Path(options.output).expanduser().resolve()
            self.result=None;self.preview.setEnabled(False);self.video.setEnabled(False)
            self.start.setEnabled(False);self.cancel_button.setEnabled(True);self.cancel_button.show()
            self.workflow.set_busy(True);self.workflow.details.close();self.start.setText('Solving…' if getattr(options,'solve',False) else 'Processing…')
            self.render_succeeded=False;self.render_counter.clear();self.render_counter.hide()
            self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
            self.progress_bar.show();self.status.setText('Starting…')
            self.load_scene.setEnabled(False)
            for control in self.settings: control.setEnabled(False)
            self.append_log('Outputs: '+str(self.prepared))
            self.worker=Worker(pixels,header,options)
            self.worker.progress.connect(self.report_progress)
            self.worker.frame_progress.connect(self.show_frame_progress)
            self.worker.stage_progress.connect(self.show_stage_progress)
            self.worker.completed.connect(self.completed);self.worker.failed.connect(self.failed)
            self.worker.finished.connect(self.finished);self.worker.start()
    def render_variant(self):
        try:
            import os
            selected=Path(self.output.text()).expanduser().resolve()
            if selected!=self.prepared:
                self.use_prepared(selected,restore=False)
            if not self.prepared:
                raise ValueError('Create a flight or load a prepared field first.')
            if self.workflow.action=='render' and (not Path(self.ffmpeg.text()).is_file() or not os.access(self.ffmpeg.text(),os.X_OK)):
                raise ValueError('Choose the FFmpeg executable in Tool setup → Video export.')
            if read_project(self.prepared).get('stage')=='solved':
                if not Path(self.executable.text()).is_file() or not os.access(self.executable.text(),os.X_OK):
                    raise ValueError('Choose the star-removal executable in Tool setup before preparing the project.')
                date=self.epoch.text().strip() or read_project(self.prepared).get('epoch','')
                if not date: raise ValueError('Enter the observation date in Prepare image before preparing the project.')
                if not self.selected_date_info(): raise ValueError('Enter a valid capture year or date.')
            selected=self.selected_date_info()
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),zoom_mode=self.zoom_mode.currentData(),travel_pc=self.travel_pc.value(),target_distance_pc=self.target_distance_pc.value(),target_info=self.target_info,approximate_distances=self.approximate_distances.isChecked(),max_stars=self.star_limit.value(),mode="iterative",
                output=str(self.prepared),ffmpeg=self.ffmpeg.text(),reuse=True,layers_only=self.workflow.action=='layers',prepare_only=self.workflow.action=='calculate',fps=self.workflow.fps.currentData(),video_width=self.workflow.resolution.currentData(),
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=self.executable.text(),epoch=selected['value'] if selected else '',date_info=selected)
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def load_prepared(self):
        selected=QFileDialog.getExistingDirectory(self,'Choose a SPACER project or an older prepared run folder',self.preferences.directory('project_directory'))
        if not selected: return
        try: self.use_prepared(Path(selected))
        except Exception as exc:
            QMessageBox.warning(self,'Prepared field missing',str(exc));return
    def use_prepared(self,folder,restore=True):
        folder=Path(folder).expanduser().resolve()
        state=read_project(folder)
        try: active=calculation_folder(folder)
        except ValueError: active=None  # Keep the cached-layer recalculation action available.
        if active is not None and (active/'scene_iterative.json').exists():
            import json
            saved_scene=json.loads((active/'scene_iterative.json').read_text())
        else:
            saved_scene=load_prepared_scene(folder) if active is not None and ((folder/'scene.json').exists() or (folder/'preview.html').exists()) else {}
        if not saved_scene and not state and not (folder/'scene_iterative.json').exists():
            raise ValueError('This folder is not a SPACER project.')
        if restore:
            self.seconds.setValue(state.get('seconds',60))
            self.workflow.fps.setCurrentIndex(max(0,self.workflow.fps.findData(state.get('fps',24))))
            self.workflow.resolution.setCurrentIndex(max(0,self.workflow.resolution.findData(state.get('video_width',1920))))
            self.zoom.setValue(1+state.get('zoom',30)/100)
            self.travel_pc.setValue(state.get('travel_pc',80))
            self.clear_target_origin()
            self.target_distance_pc.setValue(state.get('target_distance_pc',0))
            self.target_info=state.get('target_info')
            # Discard catalogue selections inherited from a different field.
            if self.target_info and all(key in self.target_info for key in ('ra_deg','dec_deg')) and (folder/'source_wcs.fits').is_file():
                from astropy.io import fits
                from targets import in_field
                from astropy.wcs import WCS
                target_header=fits.getheader(folder/'source_wcs.fits')
                if not in_field(WCS(target_header,naxis=2).celestial,target_header['NAXIS1'],target_header['NAXIS2'],self.target_info['ra_deg'],self.target_info['dec_deg']):
                    self.reset_target_distance()
            if self.target_info:self.target_origin.setText(f"{self.target_info['name']} · SIMBAD distance" + (" (approximate)" if self.target_info.get("approximate") else ""))
            self.zoom_mode.setCurrentIndex(max(0,self.zoom_mode.findData(state.get('zoom_mode','independent'))))
            self.star_limit.setValue(state.get('max_stars',DEFAULT_MAX_STARS))
            self.approximate_distances.setChecked(state.get('approximate_distances',saved_scene.get('distance_coverage',{}).get('enabled',False)))
            if state.get('ffmpeg'): self.ffmpeg.setText(state['ffmpeg'])
            if 'engine' in state:
                self.engine.setCurrentIndex(0 if state['engine']=='StarXTerminator' else 1)
            if 'executable' in state:
                self.executable.setText(state.get('executable',''))
            saved_date=state.get('date_info') or saved_scene.get('date_info') or date_info(state.get('epoch',''),'Saved project date (source unrecorded)',True)
            if not saved_date and state.get('stage')=='solved' and (folder/'source_wcs.fits').is_file():
                from astropy.io import fits
                original=Path(state.get('source') or folder/'source_wcs.fits')
                if not original.is_file(): original=folder/'source_wcs.fits'
                saved_date=infer_photo_date(original,fits.getheader(folder/'source_wcs.fits'))
            self.set_date_info(saved_date)
            solver=state.get('astrometry',{})
            if solver.get('executable'): self.astap.setText(solver['executable'])
            if solver.get('database'): self.database.setText(solver['database'])
        self.refresh_motion_ui()
        self.restore_export_links(folder)
        if folder!=self.prepared:
            self.render_succeeded=False;self.progress_bar.hide();self.render_counter.hide()
        self.prepared_approximate=saved_scene.get('distance_coverage',{}).get('enabled',False) if saved_scene else None
        coverage=saved_scene.get('distance_coverage',{})
        self.calculation_hint.setToolTip('\n'.join(f'{source}: {count:,}' for source,count in coverage.get('by_source',{}).items()))
        self.prepared_star_limit=saved_scene.get('motion_selection',{}).get('limit')
        self.prepared_star_count=len(saved_scene['stars']) if 'stars' in saved_scene else None
        self.prepared=folder;self.output.setText(str(folder));self.refresh_project()
        self.remember_project(folder)
        if restore:
            self.workflow.pending_step=2 if self.workflow.ready else (1 if self.workflow.layers else 0)
            if not self.workflow.busy:self.workflow.go(self.workflow.pending_step)
        self.append_log(f'Tool v{VERSION} · saved field {field_description(saved_scene)}\nReusing saved image and Gaia field: '+str(folder)+
            '\nSaved image and preparation settings are used for this project.')
    def cancel(self):
        if self.worker:
            self.worker.cancel.set();self.cancel_button.setEnabled(False)
            self.report_progress('Cancelling… Waiting for the current operation to stop. Completed catalogue regions are kept.')
    def completed(self,path):
        if getattr(self.worker.options,'layers_only',False) or getattr(self.worker.options,'prepare_only',False):
            self.use_prepared(Path(path),restore=False);self.render_succeeded=True
            self.workflow.pending_step=1 if getattr(self.worker.options,'layers_only',False) else 2
            self.progress_bar.setRange(0,1000);self.progress_bar.setValue(1000);self.progress_bar.setTextVisible(True)
            self.report_progress('Image layers ready. Calculate stars to continue.' if self.workflow.pending_step==1 else 'Star calculations ready. Preview the flight before exporting.')
            return
        if getattr(self.worker.options,'solve',False):
            self.use_prepared(Path(path))
            self.report_progress('Sky position solved. The matching date is filled automatically; you can review it in Prepare image.')
            return
        if getattr(self.worker.options,'recalculate',False):
            self.use_prepared(Path(path))
            self.render_succeeded=True
            self.progress_bar.setRange(0,1000);self.progress_bar.setValue(1000);self.progress_bar.setTextVisible(True)
            self.workflow.pending_step=2
            self.report_progress('Star calculations updated. Preview the flight before exporting.')
            return
        self.render_succeeded=True
        self.use_prepared(Path(path),restore=False)
        self.progress_bar.setRange(0,1000);self.progress_bar.setValue(1000);self.progress_bar.setTextVisible(True)
        self.result=Path(path);self.result_stem=self.worker.options.result_stem;self.workflow.pending_step=3
        self.report_progress('Flight ready. Open the preview or video.');self.append_log(str(self.result/(self.result_stem+'.mp4')))
        self.preview.setEnabled(True);self.video.setEnabled(True)

    def restore_export_links(self,folder):
        self.result_stem=read_project(folder).get('last_render')
        self.result=folder if self.result_stem else None
        try: prepared_preview=(calculation_folder(folder)/'scene_iterative.json').is_file()
        except ValueError:prepared_preview=False
        self.preview.setEnabled(prepared_preview or bool(self.result and (folder/(self.result_stem+'.html')).exists()))
        self.video.setEnabled(bool(self.result and (folder/(self.result_stem+'.mp4')).exists()))
    def failed(self,message):
        if self.worker and self.worker.cancel.is_set():
            self.report_progress('Cancelled. Saved preparation and earlier exports are kept.');return
        self.report_progress(message);self.details_toggle.setChecked(True)
        QMessageBox.warning(self,'Flight not completed',message)
    def finished(self):
        self.start.setEnabled(True);self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        if not self.render_succeeded:
            self.progress_bar.hide();self.render_counter.hide()
        self.load_scene.setEnabled(True)
        self.workflow.busy=False
        for control in self.settings: control.setEnabled(True)
        if self.prepared and (self.prepared/'project.json').is_file(): self.remember_project(self.prepared)
        message=self.status.text()
        self.refresh_project()
        if self.prepared: self.restore_export_links(self.prepared)
        self.status.setText(message)
        self.workflow.set_busy(False)
        if hasattr(self.workflow,'pending_step'):
            self.workflow.go(self.workflow.pending_step);del self.workflow.pending_step
    def open_result(self,name):
        if self.result:
            suffix='.html' if name=='preview.html' else '.mp4'
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result/(self.result_stem+suffix))))
    def open_preview(self):
        if self.workflow.ready:self.workflow.go(2);return
        folder=Path(self.output.text()).expanduser().resolve()
        path=folder/(self.result_stem+'.html') if self.result_stem else folder/'preview.html'
        if path.is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def apply_preview_settings(self,values,folder):
        if Path(self.output.text()).expanduser().resolve()!=folder or (self.worker and self.worker.isRunning()):
            self.show_problem('Preview belongs to another state','Return to this preview’s project and wait for processing to finish before applying settings.');return
        self.seconds.setValue(values['seconds']);self.zoom.setValue(values['zoom'])
        self.travel_pc.setValue(values['travel_pc']);self.target_distance_pc.setValue(values['target_distance_pc'])
        self.zoom_mode.setCurrentIndex(self.zoom_mode.findData(values['zoom_mode']));self.refresh_motion_ui()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.report_progress('Processing is running. Cancel and wait for it to stop before closing.');event.ignore();return
        if self.target_worker and self.target_worker.isRunning():
            self.report_progress('Wait for the target lookup to finish before closing.');event.ignore();return
        if not self.workflow.preview.shutdown():event.ignore();return
        self.workflow.save_tools();self.workflow.details.close();event.accept()
