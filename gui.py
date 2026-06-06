import re
import sys
from PySide6 import QtCore, QtGui, QtWidgets
from test import generate_initial_exam, regenerate_specific_question, generate_word_document, extract_exam_sections, extract_reading_passage, get_exam_folders

def _apply_rtl(widget):
    widget.setLayoutDirection(QtCore.Qt.RightToLeft)
    widget.setAlignment(QtCore.Qt.AlignRight)
    if isinstance(widget, QtWidgets.QTextEdit):
        option = widget.document().defaultTextOption()
        option.setTextDirection(QtCore.Qt.RightToLeft)
        widget.document().setDefaultTextOption(option)


class Worker(QtCore.QObject):
    finished = QtCore.Signal(object)
    error = QtCore.Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @QtCore.Slot()
    def run(self):
        try:
            result = self.fn()
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.finished.emit(result)


class CallbackProxy(QtCore.QObject):
    def __init__(self, on_success, on_error, parent=None):
        super().__init__(parent)
        self._on_success = on_success
        self._on_error = on_error

    @QtCore.Slot(object)
    def success(self, result):
        self._on_success(result)

    @QtCore.Slot(str)
    def error(self, message):
        self._on_error(message)


class ArabicExamGeneratorGUI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("منشئ الاختبارات العربية")
        self.resize(800, 600)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)

        self.current_exam_text = ""
        self.reading_passage = ""
        self._threads = set()
        self._workers = set()
        self._callbacks = set()

        main_layout = QtWidgets.QVBoxLayout(self)

        setup_group = QtWidgets.QGroupBox("إعدادات")
        setup_group.setAlignment(QtCore.Qt.AlignRight)
        setup_group.setLayoutDirection(QtCore.Qt.RightToLeft)
        setup_layout = QtWidgets.QGridLayout(setup_group)

        level_label = QtWidgets.QLabel("المستوى:")
        level_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        setup_layout.addWidget(level_label, 0, 0)
        self.grade_combo = QtWidgets.QComboBox()
        self.grade_combo.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.grade_combo.addItems(["2", "3", "4", "5"])
        self.grade_combo.view().setLayoutDirection(QtCore.Qt.RightToLeft)
        setup_layout.addWidget(self.grade_combo, 0, 1)

        semester_label = QtWidgets.QLabel("الفصل:")
        semester_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        setup_layout.addWidget(semester_label, 0, 2)
        self.semester_combo = QtWidgets.QComboBox()
        self.semester_combo.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.semester_combo.addItems(["1", "2", "3"])
        self.semester_combo.view().setLayoutDirection(QtCore.Qt.RightToLeft)
        setup_layout.addWidget(self.semester_combo, 0, 3)

        theme_label = QtWidgets.QLabel("الموضوع:")
        theme_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        setup_layout.addWidget(theme_label, 1, 0)
        self.theme_edit = QtWidgets.QLineEdit()
        _apply_rtl(self.theme_edit)
        setup_layout.addWidget(self.theme_edit, 1, 1, 1, 3)

        school_label = QtWidgets.QLabel("المدرسة:")
        school_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        setup_layout.addWidget(school_label, 2, 0)
        self.school_edit = QtWidgets.QLineEdit()
        _apply_rtl(self.school_edit)
        setup_layout.addWidget(self.school_edit, 2, 1)

        town_label = QtWidgets.QLabel("الولاية:")
        town_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        setup_layout.addWidget(town_label, 2, 2)
        self.town_edit = QtWidgets.QLineEdit()
        _apply_rtl(self.town_edit)
        setup_layout.addWidget(self.town_edit, 2, 3)

        generate_btn = QtWidgets.QPushButton("إنشاء الاختبار")
        generate_btn.clicked.connect(self.generate_exam)
        setup_layout.addWidget(generate_btn, 3, 0, 1, 4)

        main_layout.addWidget(setup_group)

        exam_group = QtWidgets.QGroupBox("محتوى الاختبار")
        exam_group.setAlignment(QtCore.Qt.AlignRight)
        exam_group.setLayoutDirection(QtCore.Qt.RightToLeft)
        exam_layout = QtWidgets.QVBoxLayout(exam_group)
        self.exam_text = QtWidgets.QTextEdit()
        self.exam_text.setAcceptRichText(False)
        _apply_rtl(self.exam_text)
        exam_layout.addWidget(self.exam_text)
        main_layout.addWidget(exam_group, 1)

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setDirection(QtWidgets.QBoxLayout.RightToLeft)
        edit_question_btn = QtWidgets.QPushButton("تعديل سؤال")
        edit_question_btn.clicked.connect(self.edit_question)
        buttons_layout.addWidget(edit_question_btn)

        edit_situation_btn = QtWidgets.QPushButton("تعديل الوضعية الإدماجية")
        edit_situation_btn.clicked.connect(self.edit_situation)
        buttons_layout.addWidget(edit_situation_btn)

        generate_word_btn = QtWidgets.QPushButton("إنشاء ملف Word")
        generate_word_btn.clicked.connect(self.generate_word)
        buttons_layout.addWidget(generate_word_btn)

        main_layout.addLayout(buttons_layout)

        progress_layout = QtWidgets.QHBoxLayout()
        progress_layout.setDirection(QtWidgets.QBoxLayout.RightToLeft)
        self.progress_label = QtWidgets.QLabel("جاهز")
        self.progress_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        main_layout.addLayout(progress_layout)

    def _run_in_thread(self, fn, on_success, on_error):
        thread = QtCore.QThread(self)
        worker = Worker(fn)
        callback = CallbackProxy(on_success, on_error, parent=self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(callback.success)
        worker.error.connect(callback.error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._threads.add(thread)
        self._workers.add(worker)
        self._callbacks.add(callback)
        thread.finished.connect(lambda: self._threads.discard(thread))
        thread.finished.connect(lambda: self._workers.discard(worker))
        thread.finished.connect(lambda: self._callbacks.discard(callback))
        thread.start()

    def start_progress(self, message="جاري العمل..."):
        self.progress_label.setText(message)
        self.progress_bar.setVisible(True)

    def stop_progress(self, message="جاهز"):
        self.progress_label.setText(message)
        self.progress_bar.setVisible(False)

    def generate_exam(self):
        grade = self.grade_combo.currentText()
        semester = self.semester_combo.currentText()
        theme = self.theme_edit.text().strip() or "موضوع عام"
        school = self.school_edit.text().strip() or "..."
        town = self.town_edit.text().strip() or "..."
        exam_folders = get_exam_folders(grade, semester)

        def task():
            return generate_initial_exam(theme, school, town, grade, semester, exam_folders)

        def on_success(result):
            self.stop_progress()
            if result:
                self.current_exam_text = result
                self.exam_text.setPlainText(result)
                self.reading_passage = extract_reading_passage(result)
                QtWidgets.QMessageBox.information(self, "نجاح", "تم إنشاء الاختبار بنجاح!")
            else:
                QtWidgets.QMessageBox.critical(self, "خطأ", "فشل إنشاء الاختبار")

        def on_error(message):
            self.stop_progress()
            QtWidgets.QMessageBox.critical(self, "خطأ", f"حدث خطأ: {message}")

        self.start_progress("جاري إنشاء الاختبار...")
        self._run_in_thread(task, on_success, on_error)

    def edit_question(self):
        if not self.current_exam_text:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "الرجاء إنشاء اختبار أولاً")
            return
        dialog = QuestionEditDialog(self)
        dialog.exec()

    def edit_situation(self):
        if not self.current_exam_text:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "الرجاء إنشاء اختبار أولاً")
            return
        dialog = SituationEditDialog(self)
        dialog.exec()

    def regenerate_question(self, question_id, requirements, dialog):
        def task():
            return regenerate_specific_question(
                self.current_exam_text,
                question_id,
                self.reading_passage,
                requirements,
                self.grade_combo.currentText(),
                self.semester_combo.currentText(),
            )

        def on_success(updated_exam):
            self.stop_progress()
            if updated_exam:
                self.current_exam_text = updated_exam
                self.exam_text.setPlainText(updated_exam)
                QtWidgets.QMessageBox.information(self, "نجاح", "تم تحديث السؤال بنجاح!")
                if dialog is not None:
                    dialog.accept()
            else:
                QtWidgets.QMessageBox.critical(self, "خطأ", "فشل تحديث السؤال")

        def on_error(message):
            self.stop_progress()
            QtWidgets.QMessageBox.critical(self, "خطأ", f"حدث خطأ: {message}")

        self.start_progress("جاري تحديث السؤال...")
        self._run_in_thread(task, on_success, on_error)

    def regenerate_situation(self, requirements, dialog):
        def task():
            return regenerate_specific_question(
                self.current_exam_text,
                "idmajiya",
                self.reading_passage,
                requirements,
                self.grade_combo.currentText(),
                self.semester_combo.currentText(),
            )

        def on_success(updated_exam):
            self.stop_progress()
            if updated_exam:
                self.current_exam_text = updated_exam
                self.exam_text.setPlainText(updated_exam)
                QtWidgets.QMessageBox.information(self, "نجاح", "تم تحديث الوضعية الإدماجية بنجاح!")
                if dialog is not None:
                    dialog.accept()
            else:
                QtWidgets.QMessageBox.critical(self, "خطأ", "فشل تحديث الوضعية الإدماجية")

        def on_error(message):
            self.stop_progress()
            QtWidgets.QMessageBox.critical(self, "خطأ", f"حدث خطأ: {message}")

        self.start_progress("جاري تحديث الوضعية الإدماجية...")
        self._run_in_thread(task, on_success, on_error)

    def generate_word(self):
        if not self.current_exam_text:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "الرجاء إنشاء اختبار أولاً")
            return

        school = self.school_edit.text().strip() or "..."
        town = self.town_edit.text().strip() or "..."
        semester = self.semester_combo.currentText()

        def task():
            sections = extract_exam_sections(self.current_exam_text, school, town, semester)
            return generate_word_document(sections, "arabic_exam.docx")

        def on_success(ok):
            self.stop_progress()
            if ok:
                QtWidgets.QMessageBox.information(self, "نجاح", "تم إنشاء ملف Word بنجاح!")
            else:
                QtWidgets.QMessageBox.critical(self, "خطأ", "فشل إنشاء ملف Word")

        def on_error(message):
            self.stop_progress()
            QtWidgets.QMessageBox.critical(self, "خطأ", f"حدث خطأ: {message}")

        self.start_progress("جاري إنشاء ملف Word...")
        self._run_in_thread(task, on_success, on_error)


class QuestionEditDialog(QtWidgets.QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("تعديل سؤال")
        self.resize(500, 300)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)

        layout = QtWidgets.QVBoxLayout(self)
        question_label = QtWidgets.QLabel("رقم السؤال (مثال: 1.1):")
        question_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(question_label)
        self.question_id = QtWidgets.QLineEdit()
        _apply_rtl(self.question_id)
        layout.addWidget(self.question_id)

        requirements_label = QtWidgets.QLabel("المتطلبات:")
        requirements_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(requirements_label)
        self.requirements = QtWidgets.QTextEdit()
        _apply_rtl(self.requirements)
        layout.addWidget(self.requirements)

        update_btn = QtWidgets.QPushButton("تحديث السؤال")
        update_btn.clicked.connect(self.update_question)
        layout.addWidget(update_btn)

    def update_question(self):
        question_id = self.question_id.text().strip()
        if not re.match(r"^[12]\.[1-9]$", question_id):
            QtWidgets.QMessageBox.critical(self, "خطأ", "صيغة رقم السؤال غير صحيحة")
            return
        requirements = self.requirements.toPlainText().strip()
        self.main_window.regenerate_question(question_id, requirements, self)


class SituationEditDialog(QtWidgets.QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("تعديل الوضعية الإدماجية")
        self.resize(500, 300)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)

        layout = QtWidgets.QVBoxLayout(self)
        requirements_label = QtWidgets.QLabel("المتطلبات:")
        requirements_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(requirements_label)
        self.requirements = QtWidgets.QTextEdit()
        _apply_rtl(self.requirements)
        layout.addWidget(self.requirements)

        update_btn = QtWidgets.QPushButton("تحديث الوضعية")
        update_btn.clicked.connect(self.update_situation)
        layout.addWidget(update_btn)

    def update_situation(self):
        requirements = self.requirements.toPlainText().strip()
        self.main_window.regenerate_situation(requirements, self)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setLayoutDirection(QtCore.Qt.RightToLeft)
    window = ArabicExamGeneratorGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
