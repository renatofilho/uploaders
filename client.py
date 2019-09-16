import sys
import config

from PySide2.QtCore import (
    Signal,
    QAbstractTableModel,
    QStandardPaths,
    QFile,
    QIODevice,
    Qt,
    QModelIndex,
    QMimeDatabase,
    QFileInfo,
)
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import (
    QDialog,
    QWidget,
    QFrame,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
    QTableView,
    QFileDialog,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyle,
    QSystemTrayIcon,
    QMenu,
    QMessageBox,
)
from PySide2.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QHttpMultiPart,
    QAuthenticator,
    QNetworkRequest,
    QHttpMultiPart,
    QHttpPart,
)


# Delegate for progress column, we want to display a progress bar instead of numbers
class ProgressBarDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super(ProgressBarDelegate, self).__init__(parent)

    def paint(self, painter, option, index):
        progress = index.data()

        # In case of upload error just show a 'error' string
        if progress == UploadingModel.UPLOAD_STATUS_ERROR:
            painter.setPen(Qt.red)
            painter.drawText(
                option.rect, Qt.AlignHCenter | Qt.AlignVCenter, self.tr("Error")
            )
            return

        if progress == UploadingModel.UPLOAD_STATUS_CANCEL:
            painter.drawText(
                option.rect, Qt.AlignHCenter | Qt.AlignVCenter, self.tr("Canceled")
            )
            return

        progressBarOption = QStyleOptionProgressBar()
        progressBarOption.rect = option.rect
        progressBarOption.minimum = 0
        progressBarOption.maximum = 100
        progressBarOption.progress = progress

        # If file was uploaded successful show 'Done' in the progress bar text
        if progress == UploadingModel.UPLOAD_STATUS_FINISHED:
            progressBarOption.text = self.tr("Done")
        else:
            progressBarOption.text = "%d%%" % progress

        progressBarOption.textVisible = True
        QApplication.style().drawControl(
            QStyle.CE_ProgressBar, progressBarOption, painter
        )


# Implement a model to show the active upload jobs
class UploadingModel(QAbstractTableModel):
    authenticationRequired = Signal(object)

    # Model columns
    FILE_COLUMN = 0
    PROGRESS_COLUMN = 1

    # Job status
    UPLOAD_STATUS_CANCEL = -3
    UPLOAD_STATUS_ERROR = -2
    UPLOAD_STATUS_STARTING = -1
    UPLOAD_STATUS_FINISHED = 101

    def __init__(self, parent=None):
        super(UploadingModel, self).__init__(parent)

        self.manager = QNetworkAccessManager(self)
        self.manager.authenticationRequired.connect(self.onAuthenticationRequired)
        self.manager.finished.connect(self.onUploadFinished)
        self.jobs = []

    # Start a new upload job
    def startUpload(self, filename):
        f = QFile(filename)
        if not f.open(QIODevice.ReadOnly):
            print("Upload file is not readable:", filename)
            return

        multiPart = QHttpMultiPart(QHttpMultiPart.FormDataType)
        filePart = QHttpPart()

        info = QFileInfo(f)
        db = QMimeDatabase()
        filePart.setHeader(
            QNetworkRequest.ContentTypeHeader, db.mimeTypeForFile(filename).name()
        )
        filePart.setHeader(
            QNetworkRequest.ContentDispositionHeader,
            'form-data; name="file"; filename="' + info.fileName() + '"',
        )
        filePart.setBodyDevice(f)
        multiPart.append(filePart)

        request = QNetworkRequest(config.serverUrl + "/upload")
        reply = self.manager.post(request, multiPart)

        if not reply:
            print("Failed to request upload file")
            return

        if reply.error() != QNetworkReply.NoError:
            print("Error uploading file:", reply.error())
            return

        multiPart.setParent(reply)
        reply.uploadProgress.connect(self.onUploadProgressChanged)

        actualRowCount = self.rowCount()
        self.beginInsertRows(QModelIndex(), actualRowCount, actualRowCount)
        self.jobs.append(
            {
                "file": f,
                "reply": reply,
                "progress": UploadingModel.UPLOAD_STATUS_STARTING,
            }
        )
        self.endInsertRows()

    def cancelUpload(self, index):
        job = self.jobs[index.row()]
        job["reply"].abort()

    # Ask for user and password
    def onAuthenticationRequired(self, reply, authenticator):
        self.authenticationRequired.emit(authenticator)

    # Upload job finished update job status
    def onUploadFinished(self, reply):
        status = UploadingModel.UPLOAD_STATUS_FINISHED
        if reply.error() != QNetworkReply.NoError:
            print("Upload error:", reply.error())
            if reply.error() == QNetworkReply.OperationCanceledError:
                status = UploadingModel.UPLOAD_STATUS_CANCEL
            else:
                status = UploadingModel.UPLOAD_STATUS_ERROR

        replyRow = self.indexOf(reply)
        if replyRow == -1:
            return

        replyIndex = self.index(replyRow, UploadingModel.PROGRESS_COLUMN)
        self.jobs[replyRow]["progress"] = status
        self.dataChanged.emit(replyIndex, replyIndex)

    # Update job progress
    def onUploadProgressChanged(self, bytesSent, bytesTotal):
        reply = self.sender()
        if not reply:
            return

        replyRow = self.indexOf(reply)
        if replyRow == -1:
            print("Reply not found in job list", reply, replyRow)
            return

        # avoid division by zero
        if bytesSent == 0:
            self.jobs[replyRow]["progress"] = 0
        else:
            self.jobs[replyRow]["progress"] = (bytesSent * 100) / bytesTotal

        progressIndex = self.index(replyRow, UploadingModel.PROGRESS_COLUMN)
        self.dataChanged.emit(progressIndex, progressIndex)

    # Helper function to find the model index for a specific reply object
    def indexOf(self, reply):
        for i in range(len(self.jobs)):
            if self.jobs[i]["reply"] == reply:
                return i
        return -1

    # QAbstractListModel virtual functions
    def columnCount(self, parent=QModelIndex()):
        return 2

    def rowCount(self, parent=QModelIndex()):
        return len(self.jobs)

    def data(self, index, role=Qt.DisplayRole):
        if not self.hasIndex(index.row(), index.column()):
            return None

        if role == Qt.DisplayRole:
            replyRow = index.row()
            if index.column() == UploadingModel.FILE_COLUMN:
                return self.jobs[replyRow]["file"].fileName()
            elif index.column() == UploadingModel.PROGRESS_COLUMN:
                return self.jobs[replyRow]["progress"]

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation == Qt.Vertical:
            return None

        if section == UploadingModel.FILE_COLUMN:
            return self.tr("Filename")
        elif section == UploadingModel.PROGRESS_COLUMN:
            return self.tr("Progress")

        return None

    def parent(self, index):
        return QModelIndex()


# Login window allow user to enter credentials
class LoginWindow(QDialog):
    abort = Signal()

    def __init__(self, tray, parent=None):
        super(LoginWindow, self).__init__(parent)

        self.trayIcon = tray
        frame = QFrame(self)

        frameLayout = QFormLayout()
        self.usernameField = QLineEdit(frame)
        self.passwordField = QLineEdit(frame)
        self.passwordField.setEchoMode(QLineEdit.Password)
        frameLayout.addRow(self.tr("Username"), self.usernameField)
        frameLayout.addRow(self.tr("Password"), self.passwordField)
        frame.setLayout(frameLayout)

        okButton = QPushButton(self.tr("&Ok"), frame)
        okButton.clicked.connect(self.accept)
        cancelButton = QPushButton(self.tr("&Cancel"), frame)
        cancelButton.clicked.connect(self.reject)
        buttonLayout = QHBoxLayout()
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(okButton)
        buttonLayout.addWidget(cancelButton)

        layout = QVBoxLayout()
        layout.addWidget(frame)
        layout.addLayout(buttonLayout)
        self.setLayout(layout)

    # returns username
    def username(self):
        return self.usernameField.text()

    # returns password
    def password(self):
        return self.passwordField.text()


# Application main window
class MainWindow(QWidget):
    def __init__(self, tray, parent=None):
        super(MainWindow, self).__init__(parent)

        self.tray = tray
        self.model = UploadingModel()
        self.model.authenticationRequired.connect(self.onAuthenticationRequired)

        layout = QVBoxLayout()

        # Create a table view to show upload jobs
        self.tableview = QTableView(self)
        self.tableview.setModel(self.model)
        self.tableview.setItemDelegateForColumn(
            UploadingModel.PROGRESS_COLUMN, ProgressBarDelegate(self)
        )
        self.tableview.activated.connect(self.onItemActivated)
        h = self.tableview.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.tableview, 1)

        uploadButton = QPushButton(self.tr("&Upload"), self)
        uploadButton.clicked.connect(self.onUploadButtonClicked)
        buttonsLayout = QHBoxLayout()
        buttonsLayout.addStretch(1)
        buttonsLayout.addWidget(uploadButton)

        layout.addLayout(buttonsLayout)
        self.setLayout(layout)

    # Start a new upload process
    def onUploadButtonClicked(self):
        filename = QFileDialog.getOpenFileName(
            self,
            self.tr("Select file to upload"),
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        )
        if filename == "":
            return
        self.model.startUpload(filename[0])

    # Cancel upload?
    def onItemActivated(self, index):
        reply = QMessageBox.question(
            self, self.tr("Cancel"), self.tr("Cancel upload for: %s") % index.data()
        )
        if reply == QMessageBox.Yes:
            self.model.cancelUpload(index)

    # When model require a new authentication
    def onAuthenticationRequired(self, authenticator):
        login = LoginWindow(self)
        r = login.exec_()
        login.hide()
        if r == QDialog.Accepted:
            authenticator.setUser(login.username())
            authenticator.setPassword(login.password())

    # Avoid close window when clicked on close button
    def closeEvent(self, event):
        self.hide()
        event.ignore()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    tray = QSystemTrayIcon()
    tray.setToolTip("Uploading files")
    tray.setIcon(QIcon("icon.png"))

    win = MainWindow(tray)

    menu = QMenu()
    menu.addAction(menu.tr("Quit"), app.quit)
    menu.addAction(menu.tr("Open"), win.showMaximized)
    tray.setContextMenu(menu)
    tray.show()

    win.showMaximized()

    app.exec_()
