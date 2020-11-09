# -*- coding: utf-8 -*-
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import asyncio
import difflib
import html
import json
import re
import threading
import unicodedata as ucd
from time import sleep
from typing import Callable, List, Optional, Tuple, Union

from PyQt5.QtCore import Qt

# from testing.framework.test_runner import run_tests, generate_solution_template
from testing.framework.anki_testing_api import get_solution_template, test_solution
from testing.framework.runners.console_logger import ConsoleLogger

from anki import hooks
from anki.cards import Card
from anki.lang import _, ngettext
from anki.utils import stripHTML
from aqt import AnkiQt, gui_hooks
from aqt.qt import *
from aqt.sound import av_player, getAudio, play_clicked_audio
from aqt.theme import theme_manager
from aqt.toolbar import BottomBar
from aqt.utils import (
    askUserDialog,
    downArrow,
    qtMenuShortcutWorkaround,
    run_async,
    tooltip,
)


class ReviewerBottomBar:
    def __init__(self, reviewer: Reviewer) -> None:
        self.reviewer = reviewer


THEMES = [
    "dracula",
    "github",
    "solarized-dark",
    "solarized-light",
    "railscasts",
    "monokai-sublime",
    "mono-blue",
    # "tomorrow",
    # "color-brewer",
    "zenburn",
    # "agate",
    "androidstudio",
    "atom-one-light",
    "rainbow",
    "vs",
    "atom-one-dark",
]


def replay_audio(card: Card, question_side: bool) -> None:
    if question_side:
        av_player.play_tags(card.question_av_tags())
    else:
        tags = card.answer_av_tags()
        if card.replay_question_audio_on_answer_side():
            tags = card.question_av_tags() + tags
        av_player.play_tags(tags)


class Reviewer:
    "Manage reviews.  Maintains a separate state."

    def __init__(self, mw: AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.card: Optional[Card] = None
        self.cardQueue: List[Card] = []
        self.hadCardQueue = False
        self._answeredIds: List[int] = []
        self._recordedAudio: Optional[str] = None
        self.typeCorrect: str = None  # web init happens before this is set
        self.state: Optional[str] = None
        self.bottom = BottomBar(mw, mw.bottomWeb)
        # todo:
        self.codingQuestion = False  # todo: remove this var
        self.synchronizer = threading.Event()
        self.codingBuffer = {}
        self.activeLanguage = None
        hooks.card_did_leech.append(self.onLeech)

    def show(self) -> None:
        self.mw.col.reset()
        self.mw.setStateShortcuts(self._shortcutKeys())  # type: ignore
        self.web.set_bridge_command(self._linkHandler, self)
        self.bottom.web.set_bridge_command(self._linkHandler, ReviewerBottomBar(self))
        self._reps: int = None
        self.nextCard()

    def lastCard(self) -> Optional[Card]:
        if self._answeredIds:
            if not self.card or self._answeredIds[-1] != self.card.id:
                try:
                    return self.mw.col.getCard(self._answeredIds[-1])
                except TypeError:
                    # id was deleted
                    return None
        return None

    def cleanup(self) -> None:
        gui_hooks.reviewer_will_end()

    # Fetching a card
    ##########################################################################

    def nextCard(self) -> None:
        elapsed = self.mw.col.timeboxReached()
        if elapsed:
            assert not isinstance(elapsed, bool)
            part1 = (
                ngettext("%d card studied in", "%d cards studied in", elapsed[1])
                % elapsed[1]
            )
            mins = int(round(elapsed[0] / 60))
            part2 = ngettext("%s minute.", "%s minutes.", mins) % mins
            fin = _("Finish")
            diag = askUserDialog("%s %s" % (part1, part2), [_("Continue"), fin])
            diag.setIcon(QMessageBox.Information)
            if diag.run() == fin:
                return self.mw.moveToState("deckBrowser")
            self.mw.col.startTimebox()
        if self.cardQueue:
            # undone/edited cards to show
            c = self.cardQueue.pop()
            c.startTimer()
            self.hadCardQueue = True
        else:
            if self.hadCardQueue:
                # the undone/edited cards may be sitting in the regular queue;
                # need to reset
                self.mw.col.reset()
                self.hadCardQueue = False
            c = self.mw.col.sched.getCard()
        self.card = c
        if not c:
            self.mw.moveToState("overview")
            return
        if self._reps is None or self._reps % 100 == 0:
            # we recycle the webview periodically so webkit can free memory
            self._initWeb()
        self._showQuestion()

    # Audio
    ##########################################################################

    def replayAudio(self) -> None:
        if self.state == "question":
            replay_audio(self.card, True)
        elif self.state == "answer":
            replay_audio(self.card, False)

    # Initializing the webview
    ##########################################################################

    def revHtml(self) -> str:
        extra = self.mw.col.conf.get("reviewExtra", "")
        fade = ""
        if self.mw.pm.glMode() == "software":
            fade = "<script>qFade=0;</script>"
        return """
<div id=_mark>&#x2605;</div>
<div id=_flag>&#x2691;</div>
{}
<div id=qa></div>
{}
""".format(
            fade, extra
        )

    def _initWeb(self) -> None:
        self._reps = 0
        # main window
        theme = self.mw.pm.meta["defaultCodeTheme"]
        if theme is None:
            theme = THEMES[0]
        self.web.stdHtml(
            self.revHtml(),
            css=["reviewer.css", "highlight/" + theme + ".css"],
            inactive_css=["highlight/" + t + ".css" for t in THEMES if t != theme],
            js=[
                "jquery.js",
                "browsersel.js",
                "mathjax/conf.js",
                "mathjax/MathJax.js",
                "prism.js",
                "highlight.js",
                "codejar.js",
                "reviewer.js",
            ],
            context=self,
        )
        # show answer / ease buttons
        self.bottom.web.show()
        self.bottom.web.stdHtml(
            self._bottomHTML(),
            css=["toolbar-bottom.css", "reviewer-bottom.css"],
            js=["jquery.js", "reviewer-bottom.js"],
            context=ReviewerBottomBar(self),
        )

    # Showing the question
    ##########################################################################

    def _mungeQA(self, buf: str) -> str:
        return self.typeAnsFilter(self.mw.prepare_card_text_for_display(buf))

    def _showQuestion(self) -> None:
        self._reps += 1
        self.state = "question"
        self.typedAnswer: str = None
        c = self.card
        # grab the question and play audio
        q = c.q()
        # play audio?
        if c.autoplay():
            sounds = c.question_av_tags()
            gui_hooks.reviewer_will_play_question_sounds(c, sounds)
            av_player.play_tags(sounds)
        else:
            av_player.clear_queue_and_maybe_interrupt()
            sounds = []
            gui_hooks.reviewer_will_play_question_sounds(c, sounds)
            av_player.play_tags(sounds)
        # render & update bottom
        q = self._mungeQA(q)
        q = gui_hooks.card_will_show(q, c, "reviewQuestion")

        bodyclass = theme_manager.body_classes_for_card_ord(c.ord)

        self.web.eval("_showQuestion(%s,'%s');" % (json.dumps(q), bodyclass))
        self._drawFlag()
        self._drawMark()
        self._showAnswerButton()
        # if we have a type answer field, focus main web
        if self.typeCorrect:
            self.mw.web.setFocus()
        # user hook
        gui_hooks.reviewer_did_show_question(c)

    def autoplay(self, card: Card) -> bool:
        print("use card.autoplay() instead of reviewer.autoplay(card)")
        return card.autoplay()

    def _drawFlag(self) -> None:
        self.web.eval("_drawFlag(%s);" % self.card.userFlag())

    def _drawMark(self) -> None:
        self.web.eval("_drawMark(%s);" % json.dumps(self.card.note().hasTag("marked")))

    # Showing the answer
    ##########################################################################

    def _showAnswer(self) -> None:
        if self.mw.state != "review":
            # showing resetRequired screen; ignore space
            return
        self.state = "answer"
        c = self.card
        a = c.a()
        # play audio?
        if c.autoplay():
            sounds = c.answer_av_tags()
            gui_hooks.reviewer_will_play_answer_sounds(c, sounds)
            av_player.play_tags(sounds)
        else:
            av_player.clear_queue_and_maybe_interrupt()
            sounds = []
            gui_hooks.reviewer_will_play_answer_sounds(c, sounds)
            av_player.play_tags(sounds)
        a = self._mungeQA(a)

        # check question type is coding

        a = gui_hooks.card_will_show(a, c, "reviewAnswer")
        # render and update bottom
        self.web.eval("_showAnswer(%s);" % json.dumps(a))
        self._showEaseButtons()
        # user hook
        gui_hooks.reviewer_did_show_answer(c)

    # Answering a card
    ############################################################
    def _answerCard(self, ease: int) -> None:
        "Reschedule card and show next."
        self.synchronizer.set()
        if self.mw.state != "review":
            # showing resetRequired screen; ignore key
            return
        if self.state != "answer":
            return
        if self.mw.col.sched.answerButtons(self.card) < ease:
            return
        proceed, ease = gui_hooks.reviewer_will_answer_card(
            (True, ease), self, self.card
        )
        if not proceed:
            return
        self.mw.col.sched.answerCard(self.card, ease)
        gui_hooks.reviewer_did_answer_card(self, self.card, ease)
        # here cancel the async
        self._answeredIds.append(self.card.id)
        self.mw.autosave()
        self.nextCard()

    # Handlers
    ############################################################

    def _shortcutKeys(
        self,
    ) -> List[Union[Tuple[str, Callable], Tuple[Qt.Key, Callable]]]:
        return [
            ("e", self.mw.onEditCurrent),
            (" ", self.onEnterKey),
            (Qt.Key_Return, self.onEnterKey),
            (Qt.Key_Enter, self.onEnterKey),
            ("m", self.showContextMenu),
            ("r", self.replayAudio),
            (Qt.Key_F5, self.replayAudio),
            ("Ctrl+1", lambda: self.setFlag(1)),
            ("Ctrl+2", lambda: self.setFlag(2)),
            ("Ctrl+3", lambda: self.setFlag(3)),
            ("Ctrl+4", lambda: self.setFlag(4)),
            ("*", self.onMark),
            ("=", self.onBuryNote),
            ("-", self.onBuryCard),
            ("!", self.onSuspend),
            ("@", self.onSuspendCard),
            ("Ctrl+Delete", self.onDelete),
            ("v", self.onReplayRecorded),
            ("Shift+v", self.onRecordVoice),
            ("o", self.onOptions),
            ("1", lambda: self._answerCard(1)),
            ("2", lambda: self._answerCard(2)),
            ("3", lambda: self._answerCard(3)),
            ("4", lambda: self._answerCard(4)),
            ("5", self.on_pause_audio),
            ("6", self.on_seek_backward),
            ("7", self.on_seek_forward),
        ]

    def on_pause_audio(self) -> None:
        av_player.toggle_pause()

    seek_secs = 5

    def on_seek_backward(self) -> None:
        av_player.seek_relative(-self.seek_secs)

    def on_seek_forward(self) -> None:
        av_player.seek_relative(self.seek_secs)

    def onEnterKey(self) -> None:
        if self.state == "question":
            self._getTypedAnswer()
        elif self.state == "answer":
            self.bottom.web.evalWithCallback(
                "selectedAnswerButton()", self._onAnswerButton
            )

    def _onAnswerButton(self, val: str) -> None:
        # button selected?
        if val and val in "1234":
            self._answerCard(int(val))
        else:
            self._answerCard(self._defaultEase())

    def _linkHandler(self, url: str) -> None:
        if url == "ans":
            self._getTypedAnswer()
        elif url.startswith("ease"):
            self._answerCard(int(url[4:]))
        elif url == "edit":
            self.mw.onEditCurrent()
        elif url == "selectlang":
            self.showSelectLangContextMenu()
        elif url == "selecttheme":
            self.showSelectSkinContextMenu()
        elif url == "more":
            self.showContextMenu()
        elif url == "test":
            self.web.evalWithCallback(
                "codejar ? codejar.toString() : null", self._runTests
            )
        elif url.startswith("play:"):
            play_clicked_audio(url, self.card)
        elif url.startswith("lang:"):
            lang = url.split(":")[1]
            self.onCodeLangSelected(lang)
        else:
            print("unrecognized anki link:", url)

    # Type in the answer
    ##########################################################################

    typeAnsPat = r"\[\[type:(.+?)\]\]"
    codeAnsPat = r"\[\[code:(.+?)\]\]"

    def typeAnsFilter(self, buf: str) -> str:
        if self.state == "question":
            m = re.search(self.typeAnsPat, buf)
            if m:
                return self.typeAnsQuestionFilter(buf)
            m = re.search(self.codeAnsPat, buf)
            if m:
                self.codingQuestion = True
                return self.codingQuestionFilter(buf)
            else:
                return buf
        else:
            return self.typeAnsAnswerFilter(buf)

    def codingQuestionFilter(self, buf: str) -> str:
        m = re.search(self.codeAnsPat, buf)
        fld = m.group(1)
        for f in self.card.model()["flds"]:
            if f["name"] == fld:
                self.typeCorrect = self.card.note()[f["name"]]
                self.typeFont = f["font"]
                self.typeSize = f["size"]
                break

        # todo
        # self.activeLanguage = 'java'
        return re.sub(
            self.codeAnsPat,
            # """
            #                 <select id=lang style="display:inline-block;float:right;font-size:18px;margin-bottom:10px;"
            #         onChange="pycmd('lang:' + this.value);">
            #         <option selected value="java">Java</option>
            #         <option value="python">Python</option>
            #     </select>
            # """
            """<br><br>
            <div style="width:90%%; margin: 0 auto;">
                <div class="test-toolbar">
                    <button onclick="pycmd('selectlang');">%(selLanguageLabel)s %(downArrow)s</button>
                    <button onclick="pycmd('selecttheme');">%(selSkinLabel)s %(downArrow)s</button>
                    <button onclick="pycmd('test')">Run</button>
                </div>
                <div style="position: relative">
                    <div id="codeans" style="width:100%%;height:60vh;text-align:left;" class="editor language-%(language)s" data-gramm="false">%(template)s</div>
                </div>
                <!--
                <div id=console></div>
                -->
            </div>
            </div>
            """
            % dict(
                typeFont=self.typeFont,
                typeSize=self.typeSize,
                selSkinLabel="Skin",
                selLanguageLabel="Language",
                language=self._getCurrentLang(),
                downArrow=downArrow(),
                template=get_solution_template(self.card, self._getCurrentLang()),
            ),
            buf,
        )

    def _runTests(self, src):
        self._cleanConsole()
        logger = ConsoleLogger(
            lambda txt: self.web.eval(
                "_showConsoleLog(%s);" % json.dumps(txt + "<br/>")
            )
        )
        test_solution(self.card, src, self.activeLanguage, logger)
        pass

    def _cleanConsole(self):
        self.web.eval("_cleanConsoleLog();")

    def _switchLang(self, lang, src):
        self.codingBuffer[self._getCurrentLang()] = src
        self.mw.pm.setCodeLang(lang)
        if lang in self.codingBuffer:
            src = self.codingBuffer[lang]
        else:
            src = get_solution_template(self.card, lang)
        self.web.eval("_reloadCode(%s, %s);" % (json.dumps(src), json.dumps(lang)))

    def typeAnsQuestionFilter(self, buf: str) -> str:
        self.typeCorrect = None
        clozeIdx = None
        m = re.search(self.typeAnsPat, buf)
        if not m:
            return buf
        fld = m.group(1)
        # if it's a cloze, extract data
        if fld.startswith("cloze:"):
            # get field and cloze position
            clozeIdx = self.card.ord + 1
            fld = fld.split(":")[1]
        # loop through fields for a match
        for f in self.card.model()["flds"]:
            if f["name"] == fld:
                self.typeCorrect = self.card.note()[f["name"]]
                if clozeIdx:
                    # narrow to cloze
                    self.typeCorrect = self._contentForCloze(self.typeCorrect, clozeIdx)
                self.typeFont = f["font"]
                self.typeSize = f["size"]
                break
        if not self.typeCorrect:
            if self.typeCorrect is None:
                if clozeIdx:
                    warn = _(
                        """\
Please run Tools>Empty Cards"""
                    )
                else:
                    warn = _("Type answer: unknown field %s") % fld
                return re.sub(self.typeAnsPat, warn, buf)
            else:
                # empty field, remove type answer pattern
                return re.sub(self.typeAnsPat, "", buf)
        return re.sub(
            self.typeAnsPat,
            """
<center>
<input type=text id=typeans onkeypress="_typeAnsPress();"
   style="font-family: '%s'; font-size: %spx;">
</center>
"""
            % (self.typeFont, self.typeSize),
            buf,
        )

    def log(self, text):
        self.web.eval("_showConsoleLog(%s);" % json.dumps(text + "<br/>"))

    def testCard(self, src):
        pass
        # model = self.card.model()['flds']
        # note = self.card.note()
        # funcName = note[model[1]['name']]
        # csvData = note[model[2]['name']]
        # self.synchronizer.clear()
        # run_tests(src, funcName, csvData, 'java', self.log, self.synchronizer)

    def typeAnsAnswerFilter(self, buf: str) -> str:
        if not self.typeCorrect:
            return re.sub(self.typeAnsPat, "", buf)
        origSize = len(buf)
        buf = buf.replace("<hr id=answer>", "")
        hadHR = len(buf) != origSize
        # munge correct value
        cor = self.mw.col.media.strip(self.typeCorrect)
        cor = re.sub("(\n|<br ?/?>|</?div>)+", " ", cor)
        cor = stripHTML(cor)
        # ensure we don't chomp multiple whitespace
        cor = cor.replace(" ", "&nbsp;")
        cor = html.unescape(cor)
        cor = cor.replace("\xa0", " ")
        cor = cor.strip()
        given = self.typedAnswer
        if self.codingQuestion:
            # and update the type answer area
            def repl(match):
                # can't pass a string in directly, and can't use re.escape as it
                # escapes too much
                return "<hr id=answer>"

            #     s = """
            # <span id="coding-answer" style="font-family: '%s'; font-size: %spx">%s</span>""" % (
            #         self.typeFont,
            #         self.typeSize,
            #         '',
            #     )
            #     if hadHR:
            #         # a hack to ensure the q/a separator falls before the answer
            #         # comparison when user is using {{FrontSide}}
            #         s = "<hr id=answer>" + s
            #     return s
            return re.sub(self.codeAnsPat, repl, buf)
        else:
            # compare with typed answer
            res = self.correct(given, cor, showBad=False)

            # and update the type answer area
            def repl(match):
                # can't pass a string in directly, and can't use re.escape as it
                # escapes too much
                s = """
    <span style="font-family: '%s'; font-size: %spx">%s</span>""" % (
                    self.typeFont,
                    self.typeSize,
                    res,
                )
                if hadHR:
                    # a hack to ensure the q/a separator falls before the answer
                    # comparison when user is using {{FrontSide}}
                    s = "<hr id=answer>" + s
                return s

            return re.sub(self.typeAnsPat, repl, buf)

    def _contentForCloze(self, txt: str, idx) -> str:
        matches = re.findall(r"\{\{c%s::(.+?)\}\}" % idx, txt, re.DOTALL)
        if not matches:
            return None

        def noHint(txt):
            if "::" in txt:
                return txt.split("::")[0]
            return txt

        matches = [noHint(txt) for txt in matches]
        uniqMatches = set(matches)
        if len(uniqMatches) == 1:
            txt = matches[0]
        else:
            txt = ", ".join(matches)
        return txt

    def tokenizeComparison(
        self, given: str, correct: str
    ) -> Tuple[List[Tuple[bool, str]], List[Tuple[bool, str]]]:
        # compare in NFC form so accents appear correct
        given = ucd.normalize("NFC", given)
        correct = ucd.normalize("NFC", correct)
        s = difflib.SequenceMatcher(None, given, correct, autojunk=False)
        givenElems: List[Tuple[bool, str]] = []
        correctElems: List[Tuple[bool, str]] = []
        givenPoint = 0
        correctPoint = 0
        offby = 0

        def logBad(old: int, new: int, s: str, array: List[Tuple[bool, str]]) -> None:
            if old != new:
                array.append((False, s[old:new]))

        def logGood(
            start: int, cnt: int, s: str, array: List[Tuple[bool, str]]
        ) -> None:
            if cnt:
                array.append((True, s[start : start + cnt]))

        for x, y, cnt in s.get_matching_blocks():
            # if anything was missed in correct, pad given
            if cnt and y - offby > x:
                givenElems.append((False, "-" * (y - x - offby)))
                offby = y - x
            # log any proceeding bad elems
            logBad(givenPoint, x, given, givenElems)
            logBad(correctPoint, y, correct, correctElems)
            givenPoint = x + cnt
            correctPoint = y + cnt
            # log the match
            logGood(x, cnt, given, givenElems)
            logGood(y, cnt, correct, correctElems)
        return givenElems, correctElems

    def correct(self, given: str, correct: str, showBad: bool = True) -> str:
        "Diff-corrects the typed-in answer."
        givenElems, correctElems = self.tokenizeComparison(given, correct)

        def good(s: str) -> str:
            return "<span class=typeGood>" + html.escape(s) + "</span>"

        def bad(s: str) -> str:
            return "<span class=typeBad>" + html.escape(s) + "</span>"

        def missed(s: str) -> str:
            return "<span class=typeMissed>" + html.escape(s) + "</span>"

        if given == correct:
            res = good(given)
        else:
            res = ""
            for ok, txt in givenElems:
                txt = self._noLoneMarks(txt)
                if ok:
                    res += good(txt)
                else:
                    res += bad(txt)
            res += "<br><span id=typearrow>&darr;</span><br>"
            for ok, txt in correctElems:
                txt = self._noLoneMarks(txt)
                if ok:
                    res += good(txt)
                else:
                    res += missed(txt)
        res = "<div><code id=typeans>" + res + "</code></div>"
        return res

    def _noLoneMarks(self, s: str) -> str:
        # ensure a combining character at the start does not join to
        # previous text
        if s and ucd.category(s[0]).startswith("M"):
            return "\xa0" + s
        return s

    def _getTypedAnswer(self) -> None:
        self.web.evalWithCallback("typeans ? typeans.value : null", self._onTypedAnswer)

    def _onTypedAnswer(self, val: None) -> None:
        self.typedAnswer = val or ""
        self._showAnswer()

    # Bottom bar
    ##########################################################################

    def _bottomHTML(self) -> str:
        return """
<center id=outer>
<table id=innertable width=100%% cellspacing=0 cellpadding=0>
<tr>
<td align=left width=50 valign=top class=stat>
<br>
<button title="%(editkey)s" onclick="pycmd('edit');">%(edit)s</button></td>
<td align=center valign=top id=middle>
</td>
<td width=50 align=right valign=top class=stat><span id=time class=stattxt>
</span><br>
<button onclick="pycmd('more');">%(more)s %(downArrow)s</button>
</td>
</tr>
</table>
</center>
<script>
time = %(time)d;
</script>
""" % dict(
            rem=self._remaining(),
            edit=_("Edit"),
            editkey=_("Shortcut key: %s") % "E",
            more=_("More"),
            downArrow=downArrow(),
            time=self.card.timeTaken() // 1000,
        )

    def _showAnswerButton(self) -> None:
        if not self.typeCorrect:
            self.bottom.web.setFocus()
        middle = """
<span class=stattxt>%s</span><br>
<button title="%s" id=ansbut onclick='pycmd("ans");'>%s</button>""" % (
            self._remaining(),
            _("Shortcut key: %s") % _("Space"),
            _("Show Answer"),
        )
        # wrap it in a table so it has the same top margin as the ease buttons
        middle = (
            "<table cellpadding=0><tr><td class=stat2 align=center>%s</td></tr></table>"
            % middle
        )
        if self.card.shouldShowTimer():
            maxTime = self.card.timeLimit() / 1000
        else:
            maxTime = 0
        self.bottom.web.eval("showQuestion(%s,%d);" % (json.dumps(middle), maxTime))
        self.bottom.web.adjustHeightToFit()

    def _showEaseButtons(self) -> None:
        self.bottom.web.setFocus()
        middle = self._answerButtons()
        self.bottom.web.eval("showAnswer(%s);" % json.dumps(middle))

    def _remaining(self) -> str:
        if not self.mw.col.conf["dueCounts"]:
            return ""
        if self.hadCardQueue:
            # if it's come from the undo queue, don't count it separately
            counts: List[Union[int, str]] = list(self.mw.col.sched.counts())
        else:
            counts = list(self.mw.col.sched.counts(self.card))
        idx = self.mw.col.sched.countIdx(self.card)
        counts[idx] = "<u>%s</u>" % (counts[idx])
        space = " + "
        ctxt = "<span class=new-count>%s</span>" % counts[0]
        ctxt += space + "<span class=learn-count>%s</span>" % counts[1]
        ctxt += space + "<span class=review-count>%s</span>" % counts[2]
        return ctxt

    def _defaultEase(self) -> int:
        if self.mw.col.sched.answerButtons(self.card) == 4:
            return 3
        else:
            return 2

    def _answerButtonList(self) -> Tuple[Tuple[int, str], ...]:
        button_count = self.mw.col.sched.answerButtons(self.card)
        if button_count == 2:
            buttons_tuple: Tuple[Tuple[int, str], ...] = (
                (1, _("Again")),
                (2, _("Good")),
            )
        elif button_count == 3:
            buttons_tuple = ((1, _("Again")), (2, _("Good")), (3, _("Easy")))
        else:
            buttons_tuple = (
                (1, _("Again")),
                (2, _("Hard")),
                (3, _("Good")),
                (4, _("Easy")),
            )
        buttons_tuple = gui_hooks.reviewer_will_init_answer_buttons(
            buttons_tuple, self, self.card
        )
        return buttons_tuple

    def _answerButtons(self) -> str:
        default = self._defaultEase()

        def but(i, label):
            if i == default:
                extra = "id=defease"
            else:
                extra = ""
            due = self._buttonTime(i)
            return """
<td align=center>%s<button %s title="%s" data-ease="%s" onclick='pycmd("ease%d");'>\
%s</button></td>""" % (
                due,
                extra,
                _("Shortcut key: %s") % i,
                i,
                i,
                label,
            )

        buf = "<center><table cellpading=0 cellspacing=0><tr>"
        for ease, label in self._answerButtonList():
            buf += but(ease, label)
        buf += "</tr></table>"
        script = """
<script>$(function () { $("#defease").focus(); });</script>"""
        return buf + script

    def _buttonTime(self, i: int) -> str:
        if not self.mw.col.conf["estTimes"]:
            return "<div class=spacer></div>"
        txt = self.mw.col.sched.nextIvlStr(self.card, i, True) or "&nbsp;"
        return "<span class=nobold>%s</span><br>" % txt

    # Leeches
    ##########################################################################

    def onLeech(self, card: Card) -> None:
        # for now
        s = _("Card was a leech.")
        if card.queue < 0:
            s += " " + _("It has been suspended.")
        tooltip(s)

    # Context menu
    ##########################################################################

    def _skinContextMenu(self):
        theme = self.mw.pm.meta["defaultCodeTheme"] or "dracula"
        return [
            [
                "dracula",
                "",
                lambda: self.onThemeSelected("dracula"),
                dict(checked=theme == "dracula"),
            ],
            [
                "github",
                "",
                lambda: self.onThemeSelected("github"),
                dict(checked=theme == "github"),
            ],
            [
                "solarized-dark",
                "",
                lambda: self.onThemeSelected("solarized-dark"),
                dict(checked=theme == "solarized-dark"),
            ],
            [
                "solarized-light",
                "",
                lambda: self.onThemeSelected("solarized-light"),
                dict(checked=theme == "solarized-light"),
            ],
            [
                "railscasts",
                "",
                lambda: self.onThemeSelected("railcasts"),
                dict(checked=theme == "monokai-sublime"),
            ],
            [
                "monokai-sublime",
                "",
                lambda: self.onThemeSelected("monokai-sublime"),
                dict(checked=theme == "mono-blue"),
            ],
            [
                "mono-blue",
                "",
                lambda: self.onThemeSelected("mono-blue"),
                dict(checked=theme == "dracula"),
            ],
            # ["tomorrow", "", lambda: self.onThemeSelected('tomorrow')],
            # ["color-brewer", "", lambda: self.onThemeSelected('color-brewer')],
            [
                "zenburn",
                "",
                lambda: self.onThemeSelected("zenburn"),
                dict(checked=theme == "zenburn"),
            ],
            # ["agate", "", lambda: self.onThemeSelected('agate')],
            [
                "androidstudio",
                "",
                lambda: self.onThemeSelected("androidstudio"),
                dict(checked=theme == "androidstudio"),
            ],
            [
                "atom-one-light",
                "",
                lambda: self.onThemeSelected("atom-one-light"),
                dict(checked=theme == "atom-one-light"),
            ],
            [
                "rainbow",
                "",
                lambda: self.onThemeSelected("rainbow"),
                dict(checked=theme == "rainbow"),
            ],
            ["vs", "", lambda: self.onThemeSelected("vs"), dict(checked=theme == "vs")],
            [
                "atom-one-dark",
                "",
                lambda: self.onThemeSelected("atom-one-dark"),
                dict(checked=theme == "atom-one-dark"),
            ],
        ]

    def _langContextMenu(self):
        lang = self._getCurrentLang()
        return [
            [
                "Java",
                "j",
                lambda: self.onCodeLangSelected("java"),
                dict(checked=lang == "java"),
            ],
            [
                "Python",
                "p",
                lambda: self.onCodeLangSelected("python"),
                dict(checked=lang == "python"),
            ],
        ]

    def _getCurrentLang(self):
        lang = self.mw.pm.meta["defaultCodeLang"]
        if lang is None:
            lang = "java"
        return lang

    # note the shortcuts listed here also need to be defined above
    def _contextMenu(self):
        currentFlag = self.card and self.card.userFlag()
        opts = [
            [
                _("Flag Card"),
                [
                    [
                        _("Red Flag"),
                        "Ctrl+1",
                        lambda: self.setFlag(1),
                        dict(checked=currentFlag == 1),
                    ],
                    [
                        _("Orange Flag"),
                        "Ctrl+2",
                        lambda: self.setFlag(2),
                        dict(checked=currentFlag == 2),
                    ],
                    [
                        _("Green Flag"),
                        "Ctrl+3",
                        lambda: self.setFlag(3),
                        dict(checked=currentFlag == 3),
                    ],
                    [
                        _("Blue Flag"),
                        "Ctrl+4",
                        lambda: self.setFlag(4),
                        dict(checked=currentFlag == 4),
                    ],
                ],
            ],
            [_("Mark Note"), "*", self.onMark],
            [_("Bury Card"), "-", self.onBuryCard],
            [_("Bury Note"), "=", self.onBuryNote],
            [_("Suspend Card"), "@", self.onSuspendCard],
            [_("Suspend Note"), "!", self.onSuspend],
            [_("Delete Note"), "Ctrl+Delete", self.onDelete],
            [_("Options"), "O", self.onOptions],
            None,
            [_("Replay Audio"), "R", self.replayAudio],
            [_("Pause Audio"), "5", self.on_pause_audio],
            [_("Audio -5s"), "6", self.on_seek_backward],
            [_("Audio +5s"), "7", self.on_seek_forward],
            [_("Record Own Voice"), "Shift+V", self.onRecordVoice],
            [_("Replay Own Voice"), "V", self.onReplayRecorded],
        ]
        return opts

    def showSelectSkinContextMenu(self) -> None:
        opts = self._skinContextMenu()
        m = QMenu(self.mw)
        self._addMenuItems(m, opts)

        gui_hooks.reviewer_will_show_context_menu(self, m)
        qtMenuShortcutWorkaround(m)
        m.exec_(QCursor.pos())

    def showSelectLangContextMenu(self) -> None:
        opts = self._langContextMenu()
        m = QMenu(self.mw)
        self._addMenuItems(m, opts)

        gui_hooks.reviewer_will_show_context_menu(self, m)
        qtMenuShortcutWorkaround(m)
        m.exec_(QCursor.pos())

    def showContextMenu(self) -> None:
        opts = self._contextMenu()
        m = QMenu(self.mw)
        self._addMenuItems(m, opts)

        gui_hooks.reviewer_will_show_context_menu(self, m)
        qtMenuShortcutWorkaround(m)
        m.exec_(QCursor.pos())

    def _addMenuItems(self, m, rows) -> None:
        for row in rows:
            if not row:
                m.addSeparator()
                continue
            if len(row) == 2:
                subm = m.addMenu(row[0])
                self._addMenuItems(subm, row[1])
                qtMenuShortcutWorkaround(subm)
                continue
            if len(row) == 4:
                label, scut, func, opts = row
            else:
                label, scut, func = row
                opts = {}
            a = m.addAction(label)
            if scut:
                a.setShortcut(QKeySequence(scut))
            if opts.get("checked"):
                a.setCheckable(True)
                a.setChecked(True)
            qconnect(a.triggered, func)

    def onOptions(self) -> None:
        self.mw.onDeckConf(self.mw.col.decks.get(self.card.odid or self.card.did))

    def setFlag(self, flag: int) -> None:
        # need to toggle off?
        if self.card.userFlag() == flag:
            flag = 0
        self.card.setUserFlag(flag)
        self.card.flush()
        self._drawFlag()

    def onThemeSelected(self, theme) -> None:
        self.mw.pm.setCodeTheme(theme)
        self.web.eval("_switchSkin('%s');" % theme)

    def onCodeLangSelected(self, lang) -> None:
        self.web.evalWithCallback(
            "codejar ? codejar.toString() : null",
            lambda src: self._switchLang(lang, src),
        )

    def onMark(self) -> None:
        f = self.card.note()
        if f.hasTag("marked"):
            f.delTag("marked")
        else:
            f.addTag("marked")
        f.flush()
        self._drawMark()

    def onSuspend(self) -> None:
        self.mw.checkpoint(_("Suspend"))
        self.mw.col.sched.suspend_cards([c.id for c in self.card.note().cards()])
        tooltip(_("Note suspended."))
        self.mw.reset()

    def onSuspendCard(self) -> None:
        self.mw.checkpoint(_("Suspend"))
        self.mw.col.sched.suspend_cards([self.card.id])
        tooltip(_("Card suspended."))
        self.mw.reset()

    def onDelete(self) -> None:
        # need to check state because the shortcut is global to the main
        # window
        if self.mw.state != "review" or not self.card:
            return
        self.mw.checkpoint(_("Delete"))
        cnt = len(self.card.note().cards())
        self.mw.col.remove_notes([self.card.note().id])
        self.mw.reset()
        tooltip(
            ngettext(
                "Note and its %d card deleted.", "Note and its %d cards deleted.", cnt
            )
            % cnt
        )

    def onBuryCard(self) -> None:
        self.mw.checkpoint(_("Bury"))
        self.mw.col.sched.bury_cards([self.card.id])
        self.mw.reset()
        tooltip(_("Card buried."))

    def onBuryNote(self) -> None:
        self.mw.checkpoint(_("Bury"))
        self.mw.col.sched.bury_note(self.card.note())
        self.mw.reset()
        tooltip(_("Note buried."))

    def onRecordVoice(self) -> None:
        self._recordedAudio = getAudio(self.mw, encode=False)
        self.onReplayRecorded()

    def onReplayRecorded(self) -> None:
        if not self._recordedAudio:
            tooltip(_("You haven't recorded your voice yet."))
            return
        av_player.play_file(self._recordedAudio)
