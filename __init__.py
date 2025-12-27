#-------------------------------------------------------------------------------
#
# Name:        Quizlet plugin for Anki 2.0
# Purpose:     Import decks from Quizlet into Anki 2.0
# Author:
#  - Original: (c) Rolph Recto 2012, last updated 12/06/2012
#              https://github.com/rolph-recto/Anki-Quizlet
#  - Also:     Contributions from https://ankiweb.net/shared/info/1236400902
#  - Current:  JDMaybeMD
# Created:     04/07/2017
#
# Changlog:    Inital release
#               - Rolph's plugin functionality was broken, so...
#               - removed search tables and associated functions to KISS
#               - reused the original API key, dunno if that's OK
#               - replaced with just one box, for a quizlet URL
#               - added basic error handling for dummies
#
#               Update 04/09/2017
#               - modified to now take a full Quizlet url for ease of use
#               - provide feedback if trying to download a private deck
#               - return RFC 2616 response codes when error handling
#               - don't make a new card type every time a new deck imported
#               - better code documentation so people can modify it
#
#               Update 01/31/2018
#               - get original quality images instead of mobile version
#
# Changlog (by kelciour):
#               Update 09/12/2018
#               - updated to Anki 2.1
#
#               Update 04/02/2020
#               - download a set without API key since it's no longer working
#
#               Update 19/02/2020
#               - download private or password-protected sets using cookies
#
#               Update 25/02/2020
#               - make it work again by adding the User-Agent header
#
#               Update 14/04/2020
#               - try to get title from HTML a bit differently
#
#               Update 29/04/2020
#               - suggest to disable VPN if a set is blocked by a captcha
#
#               Update 04/05/2020
#               - remove Flashcards from the name of the deck
#               - rename and create a new Basic Quizlet note type if some fields doesn't exist
#
#               Update 17/05/2020
#               - use setPageData and assistantModeData as a possible source for flashcards data
#
#               Update 22/07/2020
#               - fix for Anki 2.1.28
#
#               Update 30/08/2020
#               - add Return shortcut
#
#               Update 31/08/2020
#               - add rich text formatting
#
#               Update 03/09/2020
#               - make it working again after Quizlet update

#               Update 04/09/2020
#               - move the add-on to GitHub

#               Update 17/10/2020
#               - added functionality to import multiple urls (with liutiming)

#-------------------------------------------------------------------------------
#!/usr/bin/env python

__window = None

import sys, math, time, urllib.parse, json, re, os

# Anki
from aqt import mw
from aqt.qt import *
from aqt.utils import showText
from anki.utils import checksum

import requests
import shutil

requests.packages.urllib3.disable_warnings()

sys.path.append(os.path.join(os.path.dirname(__file__), "vendor"))

from curl_cffi import requests as curl_requests


rich_text_css_light_background_colors = {
    "bgY": "#fff4e5",
    "bgB": "#cde7fa",
    "bgP": "#fde8ff"
}

rich_text_css_dark_background_colors = {
    "bgY": "#8c7620",
    "bgB": "#295f87",
    "bgP": "#7d537f",
}

rich_text_css = """
:root {
  --yellow_light_background: #fff4e5;
  --blue_light_background: #cde7fa;
  --pink_light_background: #fde8ff;
}

.nightMode {
  --yellow_light_background: #8c7620;
  --blue_light_background: #295f87;
  --pink_light_background: #7d537f;
}

.bgY {
  background-color: var(--yellow_light_background) !important;
}

.bgB {
  background-color: var(--blue_light_background) !important;
}

.bgP {
  background-color: var(--pink_light_background) !important;
}
"""

# add custom model if needed
def addCustomModel(name, col, config):

    # create custom model for imported deck
    mm = col.models
    existing = mm.by_name("Basic Quizlet")
    if existing:
        fields = mm.field_names(existing)
        if "Front" in fields and "Back" in fields and "Image" in fields:
            if not config["add_audio"]:
                return existing
            elif "Front Audio" in fields and "Back Audio" in fields:
                return existing
        else:
            existing['name'] += "-" + checksum(str(time.time()))[:5]
            mm.save(existing)
    m = mm.new("Basic Quizlet")

    # add fields
    mm.add_field(m, mm.new_field("Front"))
    mm.add_field(m, mm.new_field("Back"))
    mm.add_field(m, mm.new_field("Image"))
    mm.add_field(m, mm.new_field("Add Reverse"))
    if config["add_audio"]:
        mm.add_field(m, mm.new_field("Front Audio"))
        mm.add_field(m, mm.new_field("Back Audio"))

    # add cards
    t = mm.new_template("Forward")

    # front
    if not config["add_audio"]:
        t['qfmt'] = "{{Front}}"
        t['afmt'] = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}\n\n<div>{{Image}}</div>"
    else:
        t['qfmt'] = "{{Front}}\n\n{{#Front Audio}}\n<div>{{Front Audio}}</div>\n{{/Front Audio}}"
        t['afmt'] = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}\n\n{{#Back Audio}}<div>{{Back Audio}}</div>{{/Back Audio}}\n\n<div>{{Image}}</div>"
    mm.addTemplate(m, t)

    # back
    t = mm.new_template("Reverse")
    if not config["add_audio"]:
        t['qfmt'] = "{{#Add Reverse}}\n\n{{Back}}\n\n<div>{{Image}}</div>\n\n{{/Add Reverse}}"
        t['afmt'] = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Front}}"
    else:
        t['qfmt'] = "{{#Add Reverse}}\n\n{{Back}}\n\n{{#Back Audio}}<div>{{Back Audio}}</div>{{/Back Audio}}\n\n<div>{{Image}}</div>\n\n{{/Add Reverse}}"
        t['afmt'] = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Front}}\n\n{{#Front Audio}}\n<div>{{Front Audio}}</div>\n{{/Front Audio}}"
    mm.add_template(m, t)

    m["css"] = """.card {
    font-family: arial;
    font-size: 20px;
    line-height: 1.5;
    text-align: center;
    color: black;
    background-color: white;
}

img {
    margin-top: 1em;
}
"""

    m["css"] += rich_text_css

    if config["add_audio"]:
        m["css"] += """
.replay-button {
    margin-top: 0.5em;
}
"""

    mm.add(m)
    return m


class QuizletWindow(QWidget):

    # main window of Quizlet plugin
    def __init__(self):
        super(QuizletWindow, self).__init__()

        self.results = None
        self.thread = None
        self.closed = False

        self.config = mw.addonManager.getConfig(__name__)

        self.cookies = self.getCookies()

        self.initGUI()

    # create GUI skeleton
    def initGUI(self):

        self.box_top = QVBoxLayout()

        # left side
        self.box_left = QVBoxLayout()

        # quizlet url field
        self.box_name = QHBoxLayout()
        self.label_url = QLabel("Quizlet URL(s):")
        self.text_url = QTextEdit("",self)
        self.text_url.setAcceptRichText(False)
        self.text_url.setMinimumWidth(300)

        self.text_url.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        font_metrics = QFontMetrics(self.text_url.font())
        line_height = font_metrics.height()
        doc_margin = self.text_url.document().documentMargin()
        margins = self.text_url.contentsMargins()
        total_height = line_height + margins.top() + margins.bottom() + (2 * doc_margin)
        self.text_url.setFixedHeight(int(total_height))
        self.text_url.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_url.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_url.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        def autoResize():
            self.text_url.document().setTextWidth(self.text_url.viewport().width())
            margins = self.text_url.contentsMargins()
            height = int(self.text_url.document().size().height() + margins.top() + margins.bottom())
            self.text_url.setFixedHeight(height)
            self.resize(self.minimumSizeHint())
        self.text_url.textChanged.connect(autoResize)

        self.box_name.addWidget(self.label_url)
        self.box_name.addWidget(self.text_url)
        # parentDeck field

        self.box_parent = QHBoxLayout()
        self.label_parentDeck = QLabel("Parent deck name:")
        self.parentDeck = QLineEdit ("",self)
        self.parentDeck.setMinimumWidth(150)
        self.box_parent.addWidget(self.label_parentDeck)
        self.box_parent.addWidget(self.parentDeck)

        self.box_options = QHBoxLayout()
        self.reverse_checkbox = QCheckBox('Add Reverse?', self)
        self.reverse_checkbox.setChecked(self.config["add_reverse"])
        self.box_options.addWidget(self.reverse_checkbox)
        self.box_options.addStretch(1)

        # code (import set) button
        self.box_code = QHBoxLayout()
        self.button_code = QPushButton("Import Deck", self)
        self.button_code.setShortcut(QKeySequence("Ctrl+Return"))
        self.box_code.addStretch(1)
        self.box_code.addWidget(self.button_code)
        self.button_code.clicked.connect(self.onCode)

        # results label
        self.label_info = QLabel("This importer has three use cases: 1. single url; 2. multiple urls on multiple lines and 3. folder.\nParent deck name can be cutomized. If not provided, it will either use the folder name \n(if a folder url is provided) or save the deck as a first-level deck.")
        self.label_results = QLabel("Single url example: https://quizlet.com/vn/160732581/les-activites-flash-cards/")

        # add all widgets to top layout
        self.box_top.addLayout(self.box_name)
        self.box_top.addLayout(self.box_parent)
        self.box_top.addLayout(self.box_options)
        self.box_top.addLayout(self.box_code)
        self.box_top.addSpacing(10)
        self.box_top.addWidget(self.label_info)
        self.box_top.addSpacing(10)
        self.box_top.addWidget(self.label_results)
        self.setLayout(self.box_top)

        # go, baby go!
        self.setMinimumWidth(500)
        self.setWindowTitle("Improved Quizlet to Anki Importer")
        self.resize(self.minimumSizeHint())
        self.setWindowIcon(QIcon('icon.png'))
        self.show()

    def getCookies(self):
        cookies = {}
        if self.config["qlts"]:
            cookies = { "qlts": self.config["qlts"] }
        return cookies

    def onCode(self):
        self.config["add_reverse"] = self.reverse_checkbox.isChecked()
        mw.addonManager.writeConfig(__name__, self.config)

        parentDeck = self.parentDeck.text()
        # grab url input
        report = {'error': [], 'success': []}
        urls = self.text_url.toPlainText().splitlines()
        urls = [url.strip() for url in urls if url.strip() != ""]
        if not urls:
            return
        self.label_results.setText(("There are <b>{0}</b> urls in total. Starting".format(len(urls))))
        self.sleep(0.5)
        urls_results = []
        for url in urls:
            # voodoo needed for some error handling
            if urllib.parse.urlparse(url).scheme:
                urlDomain = urllib.parse.urlparse(url).netloc
                urlPath = urllib.parse.urlparse(url).path
            else:
                urlDomain = urllib.parse.urlparse("https://"+url).netloc
                urlPath = urllib.parse.urlparse("https://"+url).path

            # validate quizlet URL
            if url == "":
                self.label_results.setText("Oops! You forgot the deck URL :(")
                return
            elif not "quizlet.com" in urlDomain:
                self.label_results.setText("Oops! That's not a Quizlet URL :(")
                return
            self.button_code.setEnabled(False)

            if "/folders/" not in url:
                self.downloadSet(url, parentDeck)
                self.sleep(1.5)
            elif "/folders/" in url :
                r = curl_requests.get(url, cookies=self.cookies, impersonate="chrome")
                r.raise_for_status()

                regex = re.escape('<script id="__NEXT_DATA__" type="application/json">')
                regex += r'(.+?)'
                regex += re.escape('</script>')

                m = re.search(regex, r.text)

                data = m.group(1).strip()
                results = json.loads(data)["props"]["pageProps"]

                assert len(results["models"]["folder"]) == 1

                quizletFolder = results["models"]["folder"][0]
                setMap = { s["id"]:s for s in results["models"]["set"] }
                for folderSet in results["models"]["folderStudyMaterial"]:
                    if self.closed:
                        return
                    quizletSet = setMap[folderSet["setId"]]
                    if parentDeck == "":
                        self.downloadSet(quizletSet["_webUrl"], quizletFolder["name"])
                    else:
                        self.downloadSet(quizletSet["_webUrl"], parentDeck)
                    self.sleep(1.5)

            urls_results.append(self.label_results.text())

        self.button_code.setEnabled(True)

        if len(urls_results) > 1:
            self.label_results.setText('<br>'.join(urls_results))

    def closeEvent(self, evt):
        self.closed = True
        evt.accept()

    def sleep(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(0.01)
            QApplication.instance().processEvents()

    def downloadSet(self, urlPath, parentDeck=""):
        # validate and set Quizlet deck ID
        quizletDeckID = urlPath.strip("/")
        if quizletDeckID == "":
            self.label_results.setText("Oops! Please use the full deck URL :(")
            return
        elif not bool(re.search(r'\d', quizletDeckID)):
            self.label_results.setText("Oops! No deck ID found in path <i>{0}</i> :(".format(quizletDeckID))
            return
        else: # get first set of digits from url path
            quizletDeckID = re.search(r"\d+", quizletDeckID).group(0)

        # and aaawaaaay we go...
        self.label_results.setText("Connecting to Quizlet...")

        # build URL
        deck_url = "https://quizlet.com/{}/flashcards".format(quizletDeckID)

        # stop previous thread first
        # if self.thread is not None:
        #     self.thread.terminate()

        # download the data!
        self.thread = QuizletDownloader(self, deck_url, self.cookies)
        self.thread.start()

        while not self.thread.isFinished():
            mw.app.processEvents()
            self.thread.wait(50)

        # error fetching data
        if self.thread.error:
            if self.thread.errorCode == 403:
                if self.thread.errorCaptcha:
                    self.label_results.setText("Sorry, it's behind a captcha.")
                else:
                    self.label_results.setText("Sorry, this is a private deck :(")
            elif self.thread.errorCode == 404:
                self.label_results.setText("Can't find a deck with the ID <i>{0}</i>".format(quizletDeckID))
            else:
                self.label_results.setText("Unknown Error")
                showText(self.thread.errorMessage)
        else: # everything went through, let's roll!
            deck = self.thread.results
            self.label_results.setText(("Importing deck {0}...".format(deck["title"])))
            self.createDeck(deck, quizletDeckID, parentDeck)
            self.label_results.setText(("Success! Imported <b>{0}</b> ({1} cards)".format(deck["title"], deck["term_count"])))

        # self.thread.terminate()
        self.thread = None

    def createDeck(self, result, quizletDeckID, parentDeck=""):
        # create new deck and custom model
        if "set" in result:
            name = result['set']['title']
        elif "studyable" in result:
            name = result['studyable']['title']
        else:
            name = result['title']

        if parentDeck:
            name = "{}::{}".format(parentDeck, name)

        try:
            meta = result["setPage"]["pagingMeta"]
        except:
            meta = None

        if meta and meta["total"] > meta["perPage"]:
            terms = []
            page = 1
            while True:
                url = f'https://quizlet.com/webapi/3.4/studiable-item-documents?pagingToken={meta["token"]}&page={page}&perPage=100&filters%5BstudiableContainerId%5D={quizletDeckID}&filters%5BstudiableContainerType%5D=1'
                r = curl_requests.get(url, cookies=self.cookies, impersonate="chrome")
                for resp in r.json()["responses"]:
                    for item in resp["models"]["studiableItem"]:
                        d = {
                            '_imageUrl': '',
                            'wordRichText': '',
                            'definitionRichText': '',
                            'wordTTS': '',
                            'definitionTTS': '',
                        }
                        for cs in item["cardSides"]:
                            label = cs["label"]
                            for media in cs["media"]:
                                if "plainText" in media:
                                    d[label] = media["plainText"]
                                    d[f"{label}TTS"] = media["ttsUrl"]
                                    d[f"{label}RichText"] = media.get("richText", "")
                                if media['type'] == 2:
                                    d["_imageUrl"] = media["url"]
                        terms.append(d)
                if len(terms) >= meta["total"]:
                    break
                page += 1
        elif "studyModesCommon" in result:
            terms = []
            for item in result["studyModesCommon"]["studiableData"]["studiableItems"]:
                d = {
                    '_imageUrl': '',
                    'wordRichText': '',
                    'definitionRichText': '',
                    'wordTTS': '',
                    'definitionTTS': '',
                }
                for cs in item["cardSides"]:
                    label = cs["label"]
                    for media in cs["media"]:
                        if "plainText" in media:
                            d[label] = media["plainText"]
                            d[f"{label}TTS"] = media["ttsUrl"]
                            d[f"{label}RichText"] = media.get("richText", "")
                        if media['type'] == 2:
                            d["_imageUrl"] = media["url"]
                terms.append(d)
        else:
            raise Exception('NO MATCH\n\n' + result)

        result['term_count'] = len(terms)

        deck = mw.col.decks.get(mw.col.decks.id(name))
        model = addCustomModel(name, mw.col, self.config)

        # assign custom model to new deck
        mw.col.decks.select(deck["id"])
        mw.col.decks.save(deck)

        # assign new deck to custom model
        mw.col.models.set_current(model)
        model["did"] = deck["id"]
        mw.col.models.save(model)

        def getText(d, text=''):
            if not d:
                return text
            if d['type'] == 'text':
                text = d['text']
                if 'marks' in d:
                    for m in d['marks']:
                        if m['type'] in ['b', 'i', 'u']:
                            text = '<{0}>{1}</{0}>'.format(m['type'], text)
                        if 'attrs' in m:
                            attrs = " ".join(['{}="{}"'.format(k, v) for k, v in m['attrs'].items()])
                            if "class" in m['attrs']:
                                light_color = rich_text_css_light_background_colors.get(m['attrs']['class'], '')
                                dark_color = rich_text_css_dark_background_colors.get(m['attrs']['class'], '')
                            else:
                                light_color = ''
                                dark_color = ''
                            if light_color:
                                text = '<span {} style="background-color: light-dark({}, {});">{}</span>'.format(attrs, light_color, dark_color, text)
                            else:
                                text = '<span {}>{}</span>'.format(attrs, text)
                return text
            text = ''.join([getText(c) if c else '<br>' for c in d.get('content', [''])])
            if d['type'] == 'paragraph':
                text = '<div>{}</div>'.format(text)
            return text

        def ankify(text):
            text = text.replace('\n','<br>')
            text = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text)
            return text

        for idx, term in enumerate(terms, 1):
            if self.closed:
                break
            note = mw.col.newNote()
            note["Front"] = ankify(term['word'])
            note["Back"] = ankify(term['definition'])
            if self.config["rich_text_formatting"]:
                note["Front"] = getText(term['wordRichText'], note["Front"])
                note["Back"] = getText(term['definitionRichText'], note["Back"])
            if "photo" in term and term["photo"]:
                photo_urls = {
                  "1": "https://farm{1}.staticflickr.com/{2}/{3}_{4}.jpg",
                  "2": "https://o.quizlet.com/i/{1}.jpg",
                  "3": "https://o.quizlet.com/{1}.{2}"
                }
                img_tkns = term["photo"].split(',')
                img_type = img_tkns[0]
                term["_imageUrl"] = photo_urls[img_type].format(*img_tkns)
            if '_imageUrl' in term and term["_imageUrl"]:
                file_name = self.fileDownloader(term["_imageUrl"])
                if file_name:
                    note["Image"] = '<img src="{}">'.format(file_name)
                mw.app.processEvents()
            if self.config["add_audio"]:
                if term["wordTTS"]:
                    file_name = self.fileDownloader(term["wordTTS"])
                    if file_name:
                        note["Front Audio"] = '[sound:{}]'.format(file_name)
                if term["definitionTTS"]:
                    file_name = self.fileDownloader(term["definitionTTS"])
                    if file_name:
                        note["Back Audio"] = '[sound:{}]'.format(file_name)
            if self.config["add_reverse"]:
                note["Add Reverse"] = "y"
            mw.col.addNote(note)
            self.label_results.setText(("Importing deck {} [{}/{}] ...".format(name, idx, len(terms))))
            QApplication.instance().processEvents()
        # mw.col.reset()
        mw.reset()

    # download the images
    def fileDownloader(self, url):
        if '/tts/' in url:
            m = re.search(r'tts/(\w+)\.mp3\?.*&s=([^&]+)', url)
            file_name = "quizlet-" + m.group(1) + '-' + m.group(2) + ".mp3"
        else:
            url = url.replace('_m', '')
            file_name = "quizlet-" + url.split('/')[-1]
        # get original, non-mobile version of images
        r = curl_requests.get(url, impersonate="chrome")
        if r.status_code == 200:
            file_name = mw.col.media.write_data(file_name, r.content)
        else:
            file_name = ''
        return file_name

class QuizletDownloader(QThread):

    # thread that downloads results from the Quizlet API
    def __init__(self, window, url, cookies):
        super(QuizletDownloader, self).__init__()
        self.window = window

        self.url = url
        self.cookies = cookies
        self.results = None

        self.error = False
        self.errorCode = None
        self.errorCaptcha = False
        self.errorReason = None
        self.errorMessage = None

    def run(self):
        r = None
        try:
            r = curl_requests.get(self.url, cookies=self.cookies, impersonate="chrome")
            r.raise_for_status()

            regex = re.escape('<script id="__NEXT_DATA__" type="application/json">')
            regex += r'(.+?)'
            regex += re.escape('</script>')
            m = re.search(regex, r.text)

            assert m, 'NO MATCH\n\n' + text

            data = json.loads(m.group(1))["props"]["pageProps"]["dehydratedReduxStateKey"]

            self.results = json.loads(data)

            title = os.path.basename(self.url.strip()) or "Quizlet Flashcards"
            m = re.search(r'<title[^>]*>(.+?)</title>', r.text)
            if m:
                title = m.group(1)
                title = re.sub(r' Flashcards \| Quizlet$', '', title)
                title = re.sub(r' \| Quizlet$', '', title)
                title = re.sub(r'^Flashcards ', '', title)
                title = re.sub(r'\s+', ' ', title)
                title = title.strip()
            self.results['title'] = title
        except curl_requests.exceptions.HTTPError as e:
            self.error = True
            self.errorCode = e.response.status_code
            self.errorMessage = e.response.text
            if "CF-Chl-Bypass" in e.response.headers:
                self.errorCaptcha = True
        except ValueError as e:
            self.error = True
            self.errorMessage = "Invalid json: {0}".format(e)
        except Exception as e:
            self.error = True
            self.errorMessage = "{}\n-----------------\n{}".format(e, r.text if r else "")
        # yep, we got it

# plugin was called from Anki
def runQuizletPlugin():
    global __window
    __window = QuizletWindow()

# create menu item in Anki
action = QAction("Import from Quizlet", mw)
action.triggered.connect(runQuizletPlugin)
mw.form.menuTools.addAction(action)