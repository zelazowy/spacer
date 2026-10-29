"""Light-year presentation; scientific and saved values remain parsecs."""
from PyQt6.QtWidgets import QDoubleSpinBox
from PyQt6.QtGui import QValidator
from PyQt6.QtCore import QLocale

LY_PER_PC=3.261563777167433


def distance_label(pc):
    if pc is None:return 'Distance unavailable'
    return f'{float(pc)*LY_PER_PC:,.3g} ly'


class DistanceSpinBox(QDoubleSpinBox):
    """value()/setValue() use pc; text and keyboard stepping use light-years."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setKeyboardTracking(False)
        self.setDecimals(9);self.setRange(0,1e12);self.setSingleStep(1/LY_PER_PC);self.setSuffix(' ly')
    def textFromValue(self,value):
        locale=self.locale();locale.setNumberOptions(locale.numberOptions()|QLocale.NumberOption.OmitGroupSeparator)
        return locale.toString(value*LY_PER_PC,'f',3).rstrip('0').rstrip(locale.decimalPoint())
    def valueFromText(self,text):
        value,valid=self.locale().toDouble(text.replace(self.suffix(),'').strip())
        return value/LY_PER_PC if valid else self.value()
    def validate(self,text,pos):
        raw=text.replace(self.suffix(),'').strip()
        if not raw or raw==self.specialValueText():return QValidator.State.Intermediate,text,pos
        value,valid=self.locale().toDouble(raw)
        state=QValidator.State.Acceptable if valid and self.minimum()<=value/LY_PER_PC<=self.maximum() else QValidator.State.Invalid
        numeric_chars=set('0123456789'+self.locale().decimalPoint()+self.locale().groupSeparator())
        if not valid and raw and set(raw)<=numeric_chars:state=QValidator.State.Intermediate
        if raw.endswith(self.locale().decimalPoint()):state=QValidator.State.Intermediate
        return state,text,pos


class ZoomSpinBox(QDoubleSpinBox):
    """Show a direct scale without trailing zeroes, using the system locale."""
    def textFromValue(self,value):
        return self.locale().toString(value,'f',3).rstrip('0').rstrip(self.locale().decimalPoint())
