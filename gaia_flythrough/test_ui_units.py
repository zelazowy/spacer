"""Input conversion must not reinterpret saved pc values or accumulate rounding."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PyQt6.QtCore import QLocale
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import QApplication
from ui_units import DistanceSpinBox,LY_PER_PC

class DistanceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_pc_storage_and_light_year_display_and_edit(self):
        spin=DistanceSpinBox();spin.setLocale(QLocale('en_US'));spin.setValue(80)
        self.assertEqual(spin.value(),80);self.assertIn('260.925',spin.text())
        entered=spin.valueFromText('400 ly');self.assertAlmostEqual(entered,400/LY_PER_PC)
        self.assertEqual(spin.validate('400 ly',3)[0],QValidator.State.Acceptable)
        self.assertEqual(spin.validate('-1 ly',2)[0],QValidator.State.Invalid)
        for _ in range(10):spin.setValue(spin.value())
        self.assertEqual(spin.value(),80)
    def test_decimal_comma_and_keyboard_step(self):
        spin=DistanceSpinBox();spin.setLocale(QLocale('pl_PL'));spin.setValue(0)
        spin.setValue(spin.valueFromText('100,5 ly'));self.assertAlmostEqual(spin.value()*LY_PER_PC,100.5,places=6)
        before=spin.value()*LY_PER_PC;spin.stepBy(1);self.assertAlmostEqual(spin.value()*LY_PER_PC-before,1,places=6)

    def test_grouped_million_entry_can_be_typed_without_mid_edit_reformatting(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtCore import Qt
        spin=DistanceSpinBox();spin.setLocale(QLocale('de_DE'));spin.setValue(80);spin.show();spin.setFocus();spin.selectAll()
        changes=[];spin.valueChanged.connect(changes.append)
        QTest.keyClicks(spin,'1.500.000')
        self.assertEqual(spin.value(),80);self.assertEqual(changes,[])
        QTest.keyClick(spin,Qt.Key.Key_Return)
        self.assertAlmostEqual(spin.value()*LY_PER_PC,1500000,places=5)
        self.assertEqual(len(changes),1);self.assertNotIn('.',spin.text());spin.close()
