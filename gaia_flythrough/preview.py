"""Read-only, downsampled scene preparation and a native interactive preview."""
import base64
import io
import json
import math
from pathlib import Path
import threading
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image
from PyQt6.QtCore import QThread, QTimer, Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QColor, QPen
from PyQt6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QDoubleSpinBox,QSpinBox,QSlider,QCheckBox)

from density import limit_scene_stars
from flythrough import ease_progress
from motion import motion_scales,validate_motion
from version import VERSION,field_description


@dataclass
class PreviewData:
    width: int
    height: int
    background: QImage
    atlas: QImage
    stars: list
    tiles: list
    field: str
    approximate: int


def check_cancel(cancel):
    if cancel.is_set():raise InterruptedError('Preview loading cancelled.')


def rgb_image(image):
    image=image.convert('RGB')
    return QImage(image.tobytes(),image.width,image.height,image.width*3,QImage.Format.Format_RGB888).copy()


def prepare_preview(path,max_stars=50000,cancel=None,width=1200):
    """Build a bounded texture atlas without changing scene coordinates or files."""
    cancel=cancel or threading.Event();check_cancel(cancel)
    scene=json.loads(Path(path).read_text());check_cancel(cancel)
    scene,_=limit_scene_stars(scene,max_stars,cancel=cancel)
    scale=min(1,width/scene['width']);stars=[];tiles=[];patches=[]
    atlas_width=2048;x=y=2;row_height=0
    for source in scene['stars']:
        check_cancel(cancel)
        with Image.open(io.BytesIO(base64.b64decode(source['image'].split(',',1)[1]))) as image:
            patch=image.convert('RGB').resize((max(1,math.ceil(image.width*scale)),max(1,math.ceil(image.height*scale))),Image.Resampling.LANCZOS)
        if patch.width+4>atlas_width:raise ValueError('A saved star patch is too large for the lightweight preview.')
        if x+patch.width+2>atlas_width:x=2;y+=row_height+4;row_height=0
        tiles.append(QRectF(x,y,patch.width,patch.height));patches.append((patch,x,y))
        stars.append({k:v for k,v in source.items() if k!='image'})
        x+=patch.width+4;row_height=max(row_height,patch.height)
    atlas=Image.new('RGB',(atlas_width,y+row_height+2))
    for patch,x,y in patches:
        check_cancel(cancel);atlas.paste(patch,(x,y))
    with Image.open(io.BytesIO(base64.b64decode(scene['background'].split(',',1)[1]))) as image:
        image=image.convert('RGB');image.thumbnail((width,width),Image.Resampling.LANCZOS)
        background=rgb_image(image)
    check_cancel(cancel)
    return PreviewData(scene['width'],scene['height'],background,rgb_image(atlas),stars,tiles,
        field_description(scene),scene.get('distance_coverage',{}).get('approximate_stars',0))


class PreviewLoader(QThread):
    loaded=pyqtSignal(object)
    failed=pyqtSignal(str)
    def __init__(self,path,limit,parent=None):
        super().__init__(parent);self.path=path;self.limit=limit;self.cancel=threading.Event()
    def run(self):
        try:self.loaded.emit(prepare_preview(self.path,self.limit,self.cancel))
        except InterruptedError:pass
        except Exception as exc:self.failed.emit(str(exc))


class PreviewCanvas(QWidget):
    selected=pyqtSignal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.data=None;self.message='Loading lightweight preview…'
        self.position=0.;self.settings={};self.bounds=False;self.setMinimumSize(200,140)
    def set_data(self,data):
        self.data=data
        self.coords=np.array([[s[k] for k in ('x','y','depth','ax','ay','w','h')] for s in data.stars],dtype=float).reshape(-1,7)
        self.update()
    def view_rect(self):
        scale=min(self.width()/self.data.width,self.height()/self.data.height)
        return QRectF((self.width()-self.data.width*scale)/2,(self.height()-self.data.height*scale)/2,self.data.width*scale,self.data.height*scale)
    def geometry_at(self):
        settings=self.settings
        t=ease_progress(self.position,min(1.5/settings['seconds'],.49))
        z,sz,move=motion_scales(t,settings['zoom'],settings['travel_pc'],settings['zoom_mode'],settings['target_distance_pc'])
        x,y,depth,ax,ay,w,h=self.coords.T
        valid=depth>move
        k=np.divide(depth,depth-move,out=np.zeros_like(depth),where=valid)*sz
        left=self.data.width/2+(x-self.data.width/2)*k-ax*sz
        top=self.data.height/2+(y-self.data.height/2)*k-ay*sz
        valid&=(left<self.data.width)&(top<self.data.height)&(left+w*sz>0)&(top+h*sz>0)
        return z,sz,move,left,top,valid
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#10141c'))
        if not self.data or self.message:
            painter.setPen(QColor('#d8e0ec'));painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.message);return
        z,sz,_,left,top,valid=self.geometry_at();rect=self.view_rect();scale=rect.width()/self.data.width
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipRect(rect);painter.translate(rect.left(),rect.top());painter.scale(scale,scale)
        painter.drawImage(QRectF(self.data.width/2*(1-z),self.data.height/2*(1-z),self.data.width*z,self.data.height*z),self.data.background)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        indices=np.flatnonzero(valid)
        for i in indices:
            star=self.data.stars[i]
            painter.drawImage(QRectF(left[i],top[i],star['w']*sz,star['h']*sz),self.data.atlas,self.data.tiles[i])
        if self.bounds:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver);painter.setPen(QPen(QColor('#00ff88'),1/scale))
            for i in indices:
                star=self.data.stars[i];painter.drawRect(QRectF(left[i],top[i],star['w']*sz,star['h']*sz))
    def mousePressEvent(self,event):
        if not self.data or self.message or not self.data.stars:return
        rect=self.view_rect()
        if not rect.contains(event.position()):return
        scale=rect.width()/self.data.width
        px=(event.position().x()-rect.left())/scale;py=(event.position().y()-rect.top())/scale
        _,sz,_,left,top,valid=self.geometry_at()
        distances=np.hypot(left+self.coords[:,3]*sz-px,top+self.coords[:,4]*sz-py)
        distances[~valid]=np.inf;i=int(np.argmin(distances))
        if distances[i]*scale>15:return
        s=self.data.stars[i]
        source=str(s.get('source_id','Unknown ID'));source=source if source.startswith('HIP:') else 'Gaia '+source
        if s.get('distance_source')=='Hipparcos-2' and s.get('distance_catalogue_id')!=s.get('source_id'):
            source+=' / '+s.get('distance_catalogue_id','HIP ID unavailable')
        value=s.get('distance_pc',s['depth'])
        interval=f" · {s['lower_pc']:.1f}–{s['upper_pc']:.1f} pc" if 'lower_pc' in s and 'upper_pc' in s else ''
        self.selected.emit(f"{source} · {value:.1f} pc{interval} · {s.get('distance_source','Gaia geometric')}"+
            (' (approximate)' if s.get('distance_approximate') else '')+f" · original pixel {s['x']:.1f}, {s['y']:.1f}")


class PreviewWindow(QDialog):
    settings_chosen=pyqtSignal(object)
    def __init__(self,path,settings,limit=50000,parent=None,export_callback=None):
        super().__init__(parent);self.scene_path=Path(path);self.limit=limit
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
        self.setWindowTitle(f'SPACER preview — {Path(path).parent.name} — v{VERSION}')
        self.setModal(False);self.closing=False;self.loading=True;self.finished_loading=False
        self.resize(1040,780)
        available=self.screen().availableGeometry();self.resize(min(1040,available.width()-48),min(780,available.height()-64))
        layout=QVBoxLayout(self)
        self.summary=QLabel('Loading saved stars · downsampled to 1200 px · no rendering or catalogue queries');self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.controls=QWidget();rows=QVBoxLayout(self.controls);rows.setContentsMargins(0,0,0,0)
        first=QHBoxLayout();second=QHBoxLayout();rows.addLayout(first);rows.addLayout(second);layout.addWidget(self.controls)
        self.mode=QComboBox();self.mode.addItem('Camera zoom','independent');self.mode.addItem('Travel toward a target','target_distance')
        self.zoom=self.spin(1,101,3,settings['zoom'],'×')
        self.travel=self.spin(0,1e12,3,settings['travel_pc'],' pc')
        self.distance=self.spin(0,1e12,3,settings['target_distance_pc'],' pc');self.distance.setSpecialValueText('Set target distance')
        self.seconds=QSpinBox();self.seconds.setRange(4,600);self.seconds.setValue(int(settings['seconds']));self.seconds.setSuffix(' s')
        for row,label,control in [(first,'Motion',self.mode),(first,'Final zoom',self.zoom),(first,'Duration',self.seconds),
                                  (second,'Travel',self.travel),(second,'Target distance',self.distance)]:
            row.addWidget(QLabel(label));row.addWidget(control)
        self.canvas=PreviewCanvas();layout.addWidget(self.canvas,1)
        playback=QHBoxLayout();self.play=QPushButton('Play');self.play.clicked.connect(self.toggle_play)
        playback.addWidget(self.play);self.position=QSlider(Qt.Orientation.Horizontal);self.position.setRange(0,10000);self.position.setAccessibleName('Flight position');playback.addWidget(self.position,1)
        self.counter=QLabel('0.0 s');self.counter.setFixedWidth(110);self.counter.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        playback.addWidget(self.counter);layout.addLayout(playback)
        self.outlines=QCheckBox('Show extracted star boundaries');self.outlines.toggled.connect(self.set_bounds);layout.addWidget(self.outlines)
        self.selection=QLabel('Click a moving star to inspect its distance. Preview changes are temporary until you choose Use these settings.');self.selection.setWordWrap(True)
        self.selection.setFixedHeight(self.selection.fontMetrics().lineSpacing()*3+4);layout.addWidget(self.selection);self.canvas.selected.connect(self.selection.setText)
        actions=QHBoxLayout();self.apply=QPushButton('Use these settings');self.apply.clicked.connect(self.choose_settings);actions.addWidget(self.apply)
        self.export=QPushButton('Open exported HTML');self.export.setEnabled(export_callback is not None)
        if export_callback:self.export.clicked.connect(export_callback)
        actions.addWidget(self.export);actions.addStretch();close=QPushButton('Close');close.clicked.connect(self.close);actions.addWidget(close);layout.addLayout(actions)
        self.timer=QTimer(self);self.timer.setInterval(42);self.timer.timeout.connect(self.tick)
        self.mode.setCurrentIndex(max(0,self.mode.findData(settings['zoom_mode'])))
        self.position.valueChanged.connect(self.seek)
        self.position.sliderPressed.connect(self.pause)
        self.position.actionTriggered.connect(lambda _:self.pause())
        for control in (self.zoom,self.travel,self.distance,self.seconds):control.valueChanged.connect(self.changed)
        self.mode.currentIndexChanged.connect(self.changed)
        self.controls.setEnabled(False);self.play.setEnabled(False);self.apply.setEnabled(False)
        self.loader=PreviewLoader(path,limit,self);self.loader.loaded.connect(self.loaded);self.loader.failed.connect(self.failed);self.loader.finished.connect(self.load_finished)
        self.changed();self.loader.start()
    @staticmethod
    def spin(low,high,decimals,value,suffix):
        spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(decimals);spin.setValue(value);spin.setSuffix(suffix);return spin
    def values(self):
        return dict(zoom_mode=self.mode.currentData(),zoom=self.zoom.value(),travel_pc=self.travel.value(),target_distance_pc=self.distance.value(),seconds=self.seconds.value())
    def changed(self,*_):
        self.pause();settings=self.values();self.canvas.settings=settings
        target=settings['zoom_mode']=='target_distance';self.zoom.setEnabled(not target);self.distance.setEnabled(target)
        try:validate_motion(settings['zoom_mode'],settings['travel_pc'],settings['target_distance_pc']);message=''
        except ValueError:message='Set a target distance greater than travel distance.'
        if not self.loading:self.canvas.message=message
        self.play.setEnabled(not self.loading and not message);self.apply.setEnabled(not self.loading and not message)
        self.canvas.update();self.update_counter()
    def loaded(self,data):
        if self.closing:return
        self.loading=False;self.finished_loading=True;self.canvas.set_data(data);self.controls.setEnabled(True)
        self.summary.setText(f'Field {data.field} · {len(data.stars):,} moving stars ({data.approximate:,} approximate) · 1200 px preview; full-resolution exports are unchanged')
        self.changed()
    def failed(self,message):
        if self.closing:return
        self.loading=False;self.canvas.message='Cannot load preview: '+message;self.canvas.update();self.summary.setText('Preview unavailable. Saved project and exports are unchanged.')
    def load_finished(self):
        if self.closing:self.close()
    def set_bounds(self,value):self.canvas.bounds=value;self.canvas.update()
    def update_counter(self):self.counter.setText(f'{self.canvas.position*self.seconds.value():.1f} / {self.seconds.value():g} s')
    def pause(self):self.timer.stop();self.play.setText('Play')
    def seek(self,value):
        if not self.timer.isActive():self.pause()
        self.canvas.position=value/10000;self.canvas.update();self.update_counter()
    def toggle_play(self):
        if self.timer.isActive():self.pause();return
        if self.canvas.position>=1:self.position.setValue(0)
        self.started=time.monotonic()-self.canvas.position*self.seconds.value();self.timer.start();self.play.setText('Pause')
    def tick(self):
        position=min(1,(time.monotonic()-self.started)/self.seconds.value());self.position.setValue(round(position*10000))
        if position>=1:self.pause()
    def choose_settings(self):self.pause();self.settings_chosen.emit(self.values())
    def reject(self):self.close()
    def closeEvent(self,event):
        self.pause()
        if self.loader.isRunning():
            self.closing=True;self.loader.cancel.set();self.summary.setText('Closing preview…');event.ignore()
        else:event.accept()
