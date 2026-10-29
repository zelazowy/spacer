"""Dark desktop workspace and an integrated, read-only lightweight preview."""
from pathlib import Path
import os
import threading
import time

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt,QThread,QTimer,pyqtSignal
from PyQt6.QtGui import QImage,QImageReader
from PyQt6.QtWidgets import (QWidget,QFrame,QLabel,QPushButton,QToolButton,QLineEdit,
    QComboBox,QSpinBox,QDoubleSpinBox,QVBoxLayout,QHBoxLayout,QFormLayout,QListWidget,
    QStackedWidget,QScrollArea,QSlider,QCheckBox,QProgressBar,QPlainTextEdit,QDialog,
    QDialogButtonBox,QSizePolicy,QAbstractSpinBox,QFileDialog)
from preview import PreviewCanvas,PreviewLoader,rgb_image
from ui_units import DistanceSpinBox
from density import DEFAULT_MAX_STARS,MAX_MOVING_STARS
from siril_pipeline import find_tool,read_project,calculation_folder,recalculation_missing
from astap_solver import find_astap
from version import VERSION

DARK='''
QWidget {color:#e6e9ef;}
QWidget#workspace {background:#15181e;font-size:13px;}
QWidget#panel {background:transparent;}
QLabel {background:transparent;border:0;}
QLabel[muted="true"] {color:#a3adbd;}
QLabel[title="true"] {font-size:23px;font-weight:600;}
QFrame#card {background:#1c212a;border:1px solid #333d4c;border-radius:12px;}
QPushButton,QToolButton {background:#222a36;border:1px solid #46536a;border-radius:16px;padding:8px 14px;min-height:20px;color:#c4d8ff;}
QPushButton:hover,QToolButton:hover {background:#2d3c52;}
QPushButton:focus,QToolButton:focus {border:2px solid #a9c7ff;}
QPushButton[primary="true"],QPushButton:checked {background:#a9c7ff;border-color:#a9c7ff;color:#122b50;font-weight:600;}
QPushButton[quiet="true"],QToolButton {background:transparent;border-color:transparent;}
QPushButton:disabled,QToolButton:disabled {color:#727d8d;background:#222730;border-color:#343c48;}
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox {background:#191f28;color:#edf1f8;border:1px solid #59677e;border-radius:7px;padding:7px 9px;min-height:22px;selection-background-color:#355681;}
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus {border:2px solid #a9c7ff;}
QLineEdit:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled,QComboBox:disabled {color:#8490a2;border-color:#343e4d;background:#1b2028;}
QComboBox::drop-down {border:0;width:24px;}
QComboBox QAbstractItemView {background:#222a36;color:#edf1f8;selection-background-color:#354b6d;}
QListWidget {background:#1b2029;border:0;border-radius:10px;padding:8px;outline:0;}
QListWidget::item {height:42px;padding-left:10px;border-radius:8px;}
QListWidget::item:selected {background:#2d4365;color:#dce9ff;font-weight:600;}
QListWidget::item:disabled {color:#758092;}
QScrollArea,QStackedWidget {border:0;background:transparent;}
QScrollBar:vertical {background:#1a2029;width:8px;margin:0;border:0;}
QScrollBar::handle:vertical {background:#4d5c73;border-radius:4px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QSlider::groove:horizontal {height:4px;background:#39465b;border-radius:2px;}
QSlider::sub-page:horizontal {background:#a9c7ff;}
QSlider::handle:horizontal {background:#a9c7ff;border:2px solid #a9c7ff;width:14px;height:14px;margin:-5px 0;border-radius:7px;}
QCheckBox {spacing:8px;min-height:26px;}
QCheckBox::indicator {width:18px;height:18px;border:1px solid #8190a7;border-radius:3px;background:#191f28;}
QCheckBox::indicator:checked {background:#a9c7ff;border-color:#a9c7ff;image:url("CHECK_ICON");}
QCheckBox::indicator:disabled {border-color:#46536a;}
QProgressBar {background:#263143;border:0;border-radius:4px;color:#edf1f8;text-align:center;}
QProgressBar::chunk {background:#587db5;border-radius:4px;}
QPlainTextEdit {background:#111720;color:#c7d2e2;border:1px solid #46536a;selection-background-color:#355681;}
QDialog,QMessageBox {background:#15181e;}
'''


def label(value='',muted=False,title=False):
    w=QLabel(value);w.setWordWrap(True);w.setProperty('muted',muted);w.setProperty('title',title);return w


def button(value,callback=None,primary=False):
    b=QPushButton(value);b.setProperty('primary',primary)
    if callback:b.clicked.connect(callback)
    return b


def panel():
    w=QWidget();w.setObjectName('panel');v=QVBoxLayout(w);v.setContentsMargins(0,0,0,0);v.setSpacing(14);return w,v


def card(title):
    w=QFrame();w.setObjectName('card');v=QVBoxLayout(w);v.setContentsMargins(18,18,18,18);v.setSpacing(12)
    t=label(title);f=t.font();f.setBold(True);f.setPointSize(14);t.setFont(f);v.addWidget(t);return w,v


def field(v,title,control):
    host,box=panel();t=label(title);t.setBuddy(control);control.setAccessibleName(title);
    for edit in control.findChildren(QLineEdit):edit.setAccessibleName(title)
    box.setSpacing(6);box.addWidget(t);box.addWidget(control)
    host.setMinimumHeight(64);v.addWidget(host);return host


def scroll(content,width=None):
    s=QScrollArea();s.setWidgetResizable(True);s.setWidget(content)
    if width:s.setFixedWidth(width)
    return s


def disclosure(v,title,content):
    b=QToolButton();b.setText(title);b.setCheckable(True);b.setArrowType(Qt.ArrowType.RightArrow)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon);content.hide()
    def toggle(checked):
        content.setVisible(checked);b.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
    b.toggled.connect(toggle);v.addWidget(b);v.addWidget(content);return b


class PhotoLoader(QThread):
    loaded=pyqtSignal(object)
    failed=pyqtSignal(str)
    def __init__(self,path,parent=None):
        super().__init__(parent);self.path=Path(path);self.cancel=threading.Event()
    def run(self):
        try:
            if self.path.suffix.lower() in ('.fit','.fits','.fts'):
                from image_source import FileImageSource
                pixels,_=FileImageSource(self.path).snapshot(allow_unsolved=True)
                image=Image.fromarray(np.uint8(np.clip(np.flipud(np.moveaxis(pixels,0,-1)),0,1)*255))
                image.thumbnail((1200,1200),Image.Resampling.LANCZOS);result=rgb_image(image)
            else:
                reader=QImageReader(str(self.path));reader.setAutoTransform(True);size=reader.size()
                if size.isValid():size.scale(1200,1200,Qt.AspectRatioMode.KeepAspectRatio);reader.setScaledSize(size)
                result=reader.read()
                if result.isNull():raise ValueError(reader.errorString())
            if not self.cancel.is_set():self.loaded.emit(result)
        except Exception as exc:
            if not self.cancel.is_set():self.failed.emit(str(exc))


class IntegratedPreview(QWidget):
    """One canvas across all image steps; workers never touch widgets or projects."""
    def __init__(self,window):
        super().__init__();self.window=window;self.key=None;self.pending=None;self.loader=None;self.closing=False
        self.setMinimumWidth(280);v=QVBoxLayout(self);v.setContentsMargins(0,0,0,0);v.setSpacing(10)
        self.canvas=PreviewCanvas();self.canvas.message='Open an image or saved project to begin.';v.addWidget(self.canvas,1)
        row=QHBoxLayout();self.play=button('Play',self.toggle);row.addWidget(self.play)
        self.position=QSlider(Qt.Orientation.Horizontal);self.position.setRange(0,10000);self.position.setAccessibleName('Flight position');row.addWidget(self.position,1)
        self.counter=label('0:00 / 1:00');self.counter.setFixedWidth(110);row.addWidget(self.counter);v.addLayout(row)
        self.selection=label('1200 px preview · Export samples the original image.',True);self.selection.setFixedHeight(46);v.addWidget(self.selection)
        self.canvas.selected.connect(self.selection.setText)
        self.timer=QTimer(self);self.timer.setInterval(42);self.timer.timeout.connect(self.tick)
        self.position.valueChanged.connect(self.seek);self.position.sliderPressed.connect(self.pause);self.position.actionTriggered.connect(lambda _:self.pause())
        self.sync()
    def sync(self,*_):
        self.pause();w=self.window
        self.canvas.settings=dict(seconds=w.seconds.value(),zoom=w.zoom.value(),zoom_mode=w.zoom_mode.currentData(),travel_pc=w.travel_pc.value(),target_distance_pc=w.target_distance_pc.value())
        from motion import validate_motion
        try:validate_motion(w.zoom_mode.currentData(),w.travel_pc.value(),w.target_distance_pc.value());message=''
        except ValueError as exc:message=str(exc)
        if self.canvas.data:self.canvas.message=message
        self.play.setEnabled(bool(self.canvas.data) and not message);self.position.setEnabled(bool(self.canvas.data) and not message)
        self.seek(self.position.value())
    def pause(self):self.timer.stop();self.play.setText('Play')
    def seek(self,value):
        self.canvas.position=value/10000;self.canvas.update();s=self.window.seconds.value();t=self.canvas.position*s
        self.counter.setText(f'{int(t)//60}:{int(t)%60:02d} / {s//60}:{s%60:02d}')
    def toggle(self):
        if self.timer.isActive():self.pause();return
        if self.position.value()==10000:self.position.setValue(0)
        self.started=time.monotonic()-self.canvas.position*self.window.seconds.value();self.timer.start();self.play.setText('Pause')
    def tick(self):
        value=min(10000,round((time.monotonic()-self.started)/self.window.seconds.value()*10000));self.position.setValue(value)
        if value==10000:self.pause()
    def load(self,path,scene=False):
        key=(str(path) if path else None,scene,self.window.star_limit.value())
        if key==self.key:return
        self.key=key;self.pause();self.position.setValue(0);self.canvas.data=None;self.canvas.photo=None
        self.canvas.message='Loading preview…' if path else 'Open an image or saved project to begin.';self.canvas.update();self.sync()
        self.pending=(key,path,scene)
        if self.loader is not None:self.loader.cancel.set();return
        self.start_pending()
    def start_pending(self):
        if self.closing or not self.pending:return
        key,path,scene=self.pending;self.pending=None
        if not path:return
        loader=PreviewLoader(path,self.window.star_limit.value(),self) if scene else PhotoLoader(path,self)
        self.loader=loader
        loader.preview_key=key;loader.is_scene=scene
        loader.loaded.connect(self.receive_data)
        loader.failed.connect(self.receive_failure);loader.finished.connect(self.finished);loader.start()
    def receive_data(self,data):
        sender=self.sender();self.loaded(sender.preview_key,sender.is_scene,data)
    def receive_failure(self,message):
        self.failed(self.sender().preview_key,message)
    def loaded(self,key,scene,data):
        if self.closing or key!=self.key:return
        if scene:
            self.canvas.set_data(data);self.selection.setText(f'{len(data.stars):,} moving stars · field {data.field} · click a star to inspect.')
        else:self.canvas.photo=data;self.canvas.message='';self.canvas.update()
        self.sync()
    def failed(self,key,msg):
        if not self.closing and key==self.key:
            self.canvas.message='Preview unavailable. See Details.';self.canvas.update();self.window.append_log(msg)
    def finished(self):
        old=self.loader;self.loader=None
        if old:old.deleteLater()
        if self.closing:self.window.close()
        else:self.start_pending()
    def shutdown(self):
        self.closing=True;self.pending=None;self.pause()
        if self.loader is not None:self.loader.cancel.set();return False
        return True


class Workspace:
    def __init__(self,w):
        self.w=w;self.step=0;self.action='render';self.ready=False;self.layers=False;self.busy=False
        w.setObjectName('workspace');w.setStyleSheet(DARK.replace('CHECK_ICON',str(Path(__file__).with_name('icons')/'check.svg')))
        available=w.screen().availableGeometry();w.resize(min(1440,available.width()-48),min(900,available.height()-64))
        outer=QVBoxLayout(w);outer.setContentsMargins(0,0,0,0)
        w.main_scroll=QScrollArea();w.main_scroll.setWidgetResizable(True);w.main_content=QWidget();w.main_content.setObjectName('panel');w.main_content.setMinimumSize(990,680);w.main_scroll.setWidget(w.main_content);outer.addWidget(w.main_scroll)
        layout=QVBoxLayout(w.main_content);layout.setContentsMargins(24,20,24,16);layout.setSpacing(16)
        w.header=QWidget();header=QHBoxLayout(w.header);header.setContentsMargins(0,0,0,0)
        w.heading=label('SPACER',title=True);header.addWidget(w.heading);header.addSpacing(20)
        w.project_title=label('No image selected');w.project_title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);header.addWidget(w.project_title,1)
        w.new_project=button('New from Siril…' if w.siril else 'Open image…',w.new_from_siril if w.siril else w.open_image);header.addWidget(w.new_project)
        w.load_scene=button('Open project…',w.load_prepared);header.addWidget(w.load_scene)
        self.tools=button('Tool setup',lambda:self.go(4));header.addWidget(self.tools);layout.addWidget(w.header)
        body=QHBoxLayout();body.setSpacing(24)
        side,sv=panel();side.setFixedWidth(174);sv.addWidget(label('YOUR FLIGHT',True))
        self.nav=QListWidget();self.nav.addItems(['1  Prepare image','2  Calculate stars','3  Preview flight','4  Export']);self.nav.setFixedHeight(230);self.nav.currentRowChanged.connect(self.go);sv.addWidget(self.nav);sv.addStretch()
        self.folder=button('Show folder',self.show_folder);sv.addWidget(self.folder);body.addWidget(side)
        main,mv=panel();self.title=label('Prepare image',title=True);self.title.setFixedHeight(40);mv.addWidget(self.title)
        self.caption=label('',True);self.caption.setFixedHeight(38);mv.addWidget(self.caption)
        self.content=QStackedWidget();flight,fl=panel();row=QHBoxLayout();row.setSpacing(20)
        self.create_controls()
        self.preview=IntegratedPreview(w);row.addWidget(self.preview,1)
        self.panels=QStackedWidget();self.panels.setFixedWidth(350)
        for group in (w.project_group,w.advanced,w.flight_group,w.export_settings):self.panels.addWidget(scroll(group))
        row.addWidget(self.panels);fl.addLayout(row,1);self.content.addWidget(flight);self.content.addWidget(self.setup());mv.addWidget(self.content,1)
        w.activity,activity=panel();w.activity.setFixedHeight(102)
        w.status=label('Open an image or project to begin.');w.status.setFixedHeight(38);activity.setSpacing(4);activity.addWidget(w.status)
        w.progress_bar=QProgressBar();w.progress_bar.setFixedHeight(16);activity.addWidget(w.progress_bar)
        w.render_counter=label('');w.render_counter.setFixedHeight(28);activity.addWidget(w.render_counter);mv.addWidget(w.activity)
        actions=QHBoxLayout();w.preview=button('Preview',w.open_preview);actions.addWidget(w.preview);w.video=button('Open video',lambda:w.open_result('flight.mp4'));actions.addWidget(w.video)
        actions.addStretch();w.cancel_button=button('Cancel',w.cancel);actions.addWidget(w.cancel_button)
        w.start=button('Prepare image',self.primary,True);w.start.setDefault(True);actions.addWidget(w.start);mv.addLayout(actions);body.addWidget(main,1);layout.addLayout(body,1)
        bottom=QHBoxLayout();w.subtitle=label(f'v{VERSION} · Distances in light-years',True);w.subtitle.setWordWrap(False);bottom.addWidget(w.subtitle);bottom.addStretch()
        w.details_toggle=QToolButton();w.details_toggle.setText('Details');w.details_toggle.setCheckable(True);bottom.addWidget(w.details_toggle);layout.addLayout(bottom)
        w.log=QPlainTextEdit();w.log.setReadOnly(True);w.log.setMaximumBlockCount(2000);w.log.setAccessibleName('Processing details')
        self.details=QDialog(w);self.details.setWindowTitle('Processing details');self.details.resize(820,500);dl=QVBoxLayout(self.details);dl.addWidget(w.log)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);close.rejected.connect(self.details.close);dl.addWidget(close)
        w.details_toggle.toggled.connect(self.details.setVisible);self.details.finished.connect(lambda _:w.details_toggle.setChecked(False))
        w.advanced_dialog=self.details
        for item in (w.progress_bar,w.render_counter,w.cancel_button):
            policy=item.sizePolicy();policy.setRetainSizeWhenHidden(True);item.setSizePolicy(policy);item.hide()
        w.settings=[w.header,self.nav,self.content];w.output.editingFinished.connect(w.refresh_project)
        for control in (w.seconds,w.zoom,w.travel_pc,w.target_distance_pc):control.valueChanged.connect(self.preview.sync)
        w.zoom_mode.currentIndexChanged.connect(self.preview.sync);w.star_limit.valueChanged.connect(self.refresh)
        for item in w.findChildren(QAbstractSpinBox):item.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.restore_tools();self.go(0)
    def create_controls(self):
        w=self.w
        w.project_group,pv=panel();w.project_hint=label('',True);pv.addWidget(w.project_hint)
        w.preparation,prep=panel();pv.addWidget(w.preparation)
        w.stretch=QComboBox();w.stretch.addItems(['Current pixels (already stretched)','Linked autostretch (linear image)'] if w.siril else ['File pixels (already stretched)']);field(prep,'Image pixels',w.stretch)
        w.epoch=QLineEdit();w.epoch.setPlaceholderText('YYYY or YYYY-MM-DD');w.epoch.textEdited.connect(w.update_date_origin);field(prep,'Observation date',w.epoch)
        w.date_origin=label('',True);prep.addWidget(w.date_origin)
        w.new_preparation_note='Original pixels are preserved. First preparation needs a star-removal engine; star calculation needs internet.'
        w.preparation_note=label(w.new_preparation_note,True);prep.addWidget(w.preparation_note)
        w.coordinates,coords=panel();w.coordinates_hint=label('');coords.addWidget(w.coordinates_hint)
        w.target=QLineEdit();w.target.setPlaceholderText('e.g. M45');field(coords,'Object name (optional)',w.target)
        w.solve_button=button('Solve sky position',w.solve_image);coords.addWidget(w.solve_button);pv.addWidget(w.coordinates)
        w.solver_settings,solver=panel();pv.addWidget(w.solver_settings)
        w.fov=QDoubleSpinBox();w.fov.setRange(0,180);w.fov.setDecimals(3);w.fov.setSuffix('°');w.fov.setSpecialValueText('Auto');field(solver,'Image height on sky',w.fov)
        w.radius=QDoubleSpinBox();w.radius.setRange(.1,180);w.radius.setValue(180);w.radius.setSuffix('°');field(solver,'Search radius',w.radius)
        w.binning=QSpinBox();w.binning.setRange(0,8);w.binning.setSpecialValueText('Auto');field(solver,'Downsampling',w.binning)
        w.choose_coordinates=button('Choose solved FITS…',w.open_coordinates);solver.addWidget(w.choose_coordinates)
        pv.addStretch()
        w.advanced,av=panel();w.calculation_settings,cv=panel();av.addWidget(w.calculation_settings)
        w.calculation_hint=label('',True);cv.addWidget(w.calculation_hint);w.recalculation,rec=panel();cv.addWidget(w.recalculation)
        w.approximate_distances=QCheckBox('Include approximate distances');w.approximate_distances.setToolTip('Screened Hipparcos and broader Gaia estimates, with provenance retained. Apply changes with Recalculate stars.');rec.addWidget(w.approximate_distances)
        w.recalculate_button=button('Recalculate stars',w.recalculate_stars);rec.addWidget(w.recalculate_button)
        advanced,ad=panel();w.star_limit=QSpinBox();w.star_limit.setRange(100,MAX_MOVING_STARS);w.star_limit.setValue(DEFAULT_MAX_STARS);w.star_limit.setSingleStep(1000);field(ad,'Maximum moving stars',w.star_limit);disclosure(cv,'Advanced star settings',advanced)
        w.star_limit.valueChanged.connect(w.update_calculation_hint);w.approximate_distances.toggled.connect(w.update_calculation_hint);av.addStretch()
        w.flight_group,fv=panel();w.flight_form=QFormLayout();w.flight_form.setContentsMargins(0,0,0,0);w.flight_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);w.flight_form.setVerticalSpacing(10);fv.addLayout(w.flight_form)
        w.zoom_mode=QComboBox();w.zoom_mode.addItem('Camera zoom','independent');w.zoom_mode.addItem('Travel toward a target','target_distance');w.flight_form.addRow('Motion',w.zoom_mode)
        from ui_units import ZoomSpinBox
        w.zoom=ZoomSpinBox();w.zoom.setDecimals(3);w.zoom.setRange(1,101);w.zoom.setSingleStep(.1);w.zoom.setValue(1.3);w.zoom.setSuffix('×');w.flight_form.addRow('Final zoom',w.zoom)
        w.target_row,tv=panel();w.target_summary=label('No target selected');tv.addWidget(w.target_summary);w.find_targets_button=button('Choose target…',w.lookup_targets);tv.addWidget(w.find_targets_button);w.flight_form.addRow('Target',w.target_row)
        w.perspective_note=label('',True);w.flight_form.addRow(w.perspective_note)
        w.travel_pc=DistanceSpinBox();w.travel_pc.setValue(80);field(fv,'Travel distance',w.travel_pc)
        w.seconds=QSpinBox();w.seconds.setRange(4,600);w.seconds.setValue(60);w.seconds.setSuffix(' s');field(fv,'Duration',w.seconds)
        w.motion_settings,md=panel();w.target_distance_pc=DistanceSpinBox();w.target_distance_pc.setSpecialValueText('Set target distance');self.manual_distance=field(tv,'Target distance',w.target_distance_pc)
        w.target_origin=label('No target distance selected',True);md.addWidget(w.target_origin);w.motion_settings_toggle=disclosure(fv,'Distance source',w.motion_settings)
        self.bounds=QCheckBox('Show star boundaries');fv.addWidget(self.bounds);self.bounds.toggled.connect(self.set_bounds);fv.addStretch()
        w.zoom_mode.currentIndexChanged.connect(w.refresh_motion_ui);w.target_distance_pc.valueChanged.connect(w.clear_target_origin);w.travel_pc.valueChanged.connect(w.refresh_motion_ui)
        w.export_settings,ev=panel();self.export_summary=label('',True);ev.addWidget(self.export_summary)
        self.resolution=QComboBox()
        for title,value in [('1920 px wide',1920),('2560 px wide',2560),('3840 px wide',3840),('Original image size',0)]:self.resolution.addItem(title,value)
        field(ev,'Resolution',self.resolution);self.fps=QComboBox()
        for value in (24,30,60):self.fps.addItem(f'{value} fps',value)
        field(ev,'Frame rate',self.fps);ev.addWidget(label('MP4 · Original aspect ratio · No upscaling',True))
        name=w.image_filename() or 'image';w.output=QLineEdit(str(Path(name).expanduser().resolve().parent/'flythrough'/Path(name).stem));field(pv,'Project folder',w.path_row(w.output,True));self.output_note=label('',True);ev.addWidget(self.output_note)
        ev.addWidget(label('Filenames include version and flight parameters. Existing exports are kept.',True));ev.addWidget(button('Open exported HTML',lambda:w.open_result('preview.html')));ev.addStretch()
    def setup(self):
        w=self.w;host,v=panel();tabs=QHBoxLayout();self.tool_nav=[];self.tool_pages=QStackedWidget()
        for i,name in enumerate(['Star removal','Plate solving','Video export']):
            b=button(name,lambda checked=False,index=i:self.select_tool(index));b.setCheckable(True);self.tool_nav.append(b);tabs.addWidget(b)
        tabs.addStretch();v.addLayout(tabs)
        w.engine=QComboBox();w.engine.addItems(['StarXTerminator','StarNet 2.5+']);w.executable=QLineEdit();w.engine.currentIndexChanged.connect(w.choose_engine);w.choose_engine()
        if not w.executable.text() and find_tool('starnet2'):w.engine.setCurrentIndex(1)
        w.astap=QLineEdit(find_astap());w.database=QLineEdit();w.database.setPlaceholderText('Use the installed database')
        w.ffmpeg=QLineEdit(find_tool('ffmpeg'))
        self.check_results=[]
        for i in range(3):
            page,row=panel();columns=QHBoxLayout();row.addLayout(columns,1);settings,sv=panel()
            c,body=card(['Star-removal engine','Plate solving','Video export'][i]);sv.addWidget(c)
            if i==0:
                field(body,'Engine',w.engine);field(body,'Executable',w.path_row(w.executable,False));body.addWidget(label('Use the CLI installed with its required model and license. SPACER does not install engines or licenses.',True))
            elif i==1:
                field(body,'ASTAP executable',w.path_row(w.astap,False));field(body,'Star database folder',self.database_row());body.addWidget(label('Only needed for unsolved standalone images. Siril images need an existing solution.',True))
            else:field(body,'FFmpeg executable',w.path_row(w.ffmpeg,False))
            sv.addStretch();columns.addWidget(scroll(settings),1)
            aside,av=panel();aside.setFixedWidth(250);c,check=card('Installation check');result=label('Not checked',True);result.setMinimumHeight(70);check.addWidget(result);self.check_results.append(result);check.addWidget(button('Check installation',lambda checked=False,index=i:self.check_tool(index)));av.addWidget(c);av.addWidget(label('Tool paths are remembered across projects.',True));av.addStretch();columns.addWidget(aside);self.tool_pages.addWidget(page)
        v.addWidget(self.tool_pages,1);self.select_tool(0);return host
    def database_row(self):
        host,row=panel();h=QHBoxLayout();h.setContentsMargins(0,0,0,0);h.addWidget(self.w.database,1)
        def choose():
            path=QFileDialog.getExistingDirectory(self.w,'ASTAP star database',self.w.picker_directory(self.w.database.text()))
            if path:self.w.database.setText(path)
        h.addWidget(button('Browse…',choose));row.addLayout(h);return host
    def select_tool(self,index):
        self.tool_pages.setCurrentIndex(index)
        for i,b in enumerate(self.tool_nav):b.setChecked(i==index)
    def check_tool(self,index):
        w=self.w;path=Path([w.executable,w.astap,w.ffmpeg][index].text()).expanduser()
        if index==1:
            try:
                from astro_platesolve import SolveOptions,validate_backend
                validate_backend(SolveOptions(executable=str(path)))
                message='Executable available. Catalogue and sky solution are validated when solving.'
            except Exception as exc:message=str(exc)
        elif not path.is_file() or not os.access(path,os.X_OK):message='Choose an existing executable with permission to run.'
        elif index==0:message='Executable available. The engine validates its model and license when preparing an image.'
        else:message='Executable available. Encoding is checked during export.'
        self.check_results[index].setText(message);self.save_tools()
    def restore_tools(self):
        w=self.w;data=w.preferences.data.get('tools',{})
        if isinstance(data,dict):
            if data.get('engine') in (0,1):w.engine.setCurrentIndex(data['engine'])
            for name in ('executable','astap','database','ffmpeg'):
                if isinstance(data.get(name),str):getattr(w,name).setText(data[name])
        for name in ('executable','astap','database','ffmpeg'):getattr(w,name).editingFinished.connect(self.save_tools)
        w.engine.currentIndexChanged.connect(self.save_tools)
    def save_tools(self,*_):
        w=self.w;w.preferences.save(tools=dict(engine=w.engine.currentIndex(),**{name:getattr(w,name).text() for name in ('executable','astap','database','ffmpeg')}))
    def set_bounds(self,value):
        if hasattr(self,'preview'):self.preview.canvas.bounds=value;self.preview.canvas.update()
    def show_folder(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        folder=Path(self.w.output.text()).expanduser()
        if folder.is_dir():QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
    def go(self,index):
        if index<0 or self.busy:return
        self.step=index;self.content.setCurrentIndex(1 if index==4 else 0)
        if index<4:
            self.panels.setCurrentIndex(index)
            if self.nav.currentRow()!=index:self.nav.setCurrentRow(index)
        else:self.nav.clearSelection()
        self.title.setText(['Prepare image','Calculate stars','Preview flight','Export flight','Tool setup'][index])
        self.caption.setText(['Source image, plate solution and saved star-removal layers.','Match catalogue distances and separate photographed stars.','Adjust the camera and timing. Click a star to inspect its distance.','Choose output quality and save a new version of your flight.','Configure tools once. Locations are remembered across projects.'][index])
        if index!=2:self.preview.pause()
        self.refresh()
    def primary(self):
        w=self.w
        if self.step==4:self.save_tools();self.go(2 if self.ready else 0);return
        if self.step==0 and self.layers:self.go(1);return
        if self.step==1 and self.ready and not self.changed_calculation():self.go(2);return
        if self.step==2:self.go(3);return
        if self.step==1 and not recalculation_missing(Path(w.output.text())):
            self.action='calculate';w.recalculate_stars();return
        self.action='layers' if self.step==0 else ('calculate' if self.step==1 else 'render')
        self.save_tools();w.begin()
    def changed_calculation(self):
        w=self.w
        return (w.prepared_approximate is not None and w.prepared_approximate!=w.approximate_distances.isChecked()) or (w.prepared_star_limit is not None and w.star_limit.value()>w.prepared_star_limit)
    def refresh(self,*_):
        w=self.w
        if not hasattr(w,'start'):return
        folder=Path(w.output.text()).expanduser().resolve()
        try:scene=calculation_folder(folder)/'scene_iterative.json';self.ready=scene.is_file()
        except ValueError:scene=None;self.ready=False
        self.layers=all((folder/name).is_file() for name in ('photo.png','starless.png','source_wcs.fits'))
        self.folder.setEnabled(folder.is_dir())
        self.output_note.setText('Project folder: '+str(folder))
        self.export_summary.setText(f'{w.seconds.value()} seconds · {w.zoom.value():g}× zoom · {w.travel_pc.text()} travel')
        current=bool(w.siril or w.file_source or read_project(folder));unsolved=bool(not w.siril and w.file_source and not w.file_source.has_coordinates and not read_project(folder))
        allowed=[True,current,self.ready,self.ready]
        for i in range(4):
            item=self.nav.item(i);item.setFlags((item.flags()|Qt.ItemFlag.ItemIsEnabled) if allowed[i] else (item.flags()&~Qt.ItemFlag.ItemIsEnabled))
        texts=['Continue to stars' if self.layers else 'Prepare image',('Recalculate stars' if self.changed_calculation() else 'Continue to preview') if self.ready else 'Calculate stars','Continue to export','Save video','Done']
        w.start.setText(texts[self.step]);w.start.setEnabled(not self.busy and (self.step==4 or (current and not unsolved and (self.step<2 or self.ready))))
        legacy=(folder/(w.result_stem+'.html')).is_file() if w.result_stem else (folder/'preview.html').is_file()
        w.preview.setEnabled(not self.busy and (self.ready or legacy))
        self.preview.setEnabled(not self.busy)
        if not self.busy:
            photo=folder/'photo.png'
            source=scene if self.ready else (photo if photo.is_file() else (Path(w.file_source.path) if w.file_source else None))
            self.preview.load(source,self.ready);self.preview.sync()
    def set_busy(self,busy):
        self.busy=busy
        if busy:self.preview.pause()
        self.refresh()
