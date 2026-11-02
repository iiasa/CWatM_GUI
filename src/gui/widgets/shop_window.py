"""The CWatM Shop - spend the points of the CWatM account (shop.md, Step 5).

Opened by the **Shop** button in the menu bar (left of the account button), which
is shown only while logged in **and** holding the Breg badge (``AccountMixin``).

It sells **animals** for the live discharge sparkline, drawn from the server's
price list (``get_shop_items``) and the user's status (balance, earned points,
purchases): a selector with only the animals that are affordable and not owned yet
(decision 5); the owned ones listed below. The skill levels are free (not sold) and
so are the Trout and the Bottle (``account_shop.FREE_ANIMALS``).

Every purchase is confirmed first ("final - no refunds", decision 6) and decided by
the server (``buy`` -> ``shop_buy``); its answer is the new status, which the main
window takes over too (animal, account button). A bought animal becomes the
sparkline's animal.

Spending lowers the balance only - the badges and the earned points never change.
The rules are in ``account_shop`` (pure, tested); this module only shows them.
"""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLayout,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from src.gui.utils import account_shop as S
from src.gui.utils.gui_log import get_logger
from src.gui.widgets.account_dialogs import _AccountDialogBase, _open_single

log = get_logger("shop_window")

# Shop item code -> the sparkline-animal name the GUI uses
_ANIMAL_NAMES = S.ANIMAL_NAMES


def _points(n):
    return f"{n} point{'s' if n != 1 else ''}"


def _emoji(code):
    """The emoji of an animal - only in the emoji mode (else '': the icon shows it)."""
    from src.gui.widgets import discharge_sparkline as ds
    if ds.USE_IMAGE_ANIMALS:
        return ""
    names = {c: n for n, c in S.ANIMAL_CODES.items() if n in dict(ds.ANIMALS)}
    return dict(ds.ANIMALS).get(names.get(code), "")


def _icon(code):
    """The animal's picture (assets/ani) as a QIcon, or None (emoji mode / no file)."""
    from src.gui.widgets import discharge_sparkline as ds
    if not ds.USE_IMAGE_ANIMALS:
        return None
    pm = ds.animal_pixmap(_ANIMAL_NAMES.get(code))
    if pm is None:
        return None
    from PySide6.QtGui import QIcon
    return QIcon(pm)


class ShopWindow(_AccountDialogBase):
    """Buy sparkline animals with the account's points."""

    def __init__(self, mw):
        super().__init__(mw, "CWatM Shop")
        self._items = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        # the rows change after the window is shown: _grow_to_content sizes it,
        # not the layout (whose forced resize caused a Windows geometry warning)
        outer.setSizeConstraint(QLayout.SetNoConstraint)
        head = QLabel("CWatM Shop")
        head.setObjectName("accHead")
        outer.addWidget(head)
        self.lbl_balance = QLabel("")
        self.lbl_balance.setStyleSheet("font-size: 14px; font-weight: 600;")
        outer.addWidget(self.lbl_balance)
        outer.addWidget(self._note(
            "Spend the points your full CWatM runs earned on animals for the live "
            "discharge plot. Buying lowers your points - "
            "your badges stay, and a new badge still needs its full points. Purchases "
            "are final."))
        outer.addWidget(self._line())

        # everything below is rebuilt from the status on every answer
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.body, 1)
        outer.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        outer.addLayout(row)
        self._apply_style()
        self._fit(520, 460)
        self._run("get_shop_items")               # then get_status, see handle_result

    # ---- data ------------------------------------------------------------------------
    def _status(self):
        return self.mw.account_status() or {}

    def handle_result(self, op, result):
        if op == "get_shop_items":
            self._items = list(result or [])
            self._run("get_status")               # fresh balance + purchases
        elif op == "get_status":
            self._fill()
            kept, self._kept_message = getattr(self, "_kept_message", None), None
            if kept:
                self._say(kept, "warn_color")     # the refusal stays readable
        elif op == "buy":
            self._after_buy(result or {})

    def handle_error(self, op, code, message):
        if code in ("session_expired", "not_logged_in"):
            self.reject()
            return
        if op == "buy":
            # refused (not enough points, already owned, ...) - the message is shown;
            # re-read the status so the window matches the server again
            self._fill()
            self._run_quiet_refresh()
        elif op == "get_status":
            self._fill()                          # the last known status

    def _run_quiet_refresh(self):
        self._kept_message = self.status.text()
        self._run("get_status")
        self._say(self._kept_message, "warn_color")

    # ---- drawing ---------------------------------------------------------------------
    def _clear_body(self):
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                QWidget().setLayout(item.layout())      # reparent -> deleted with it

    def _fill(self):
        status = self._status()
        self.lbl_balance.setText(
            f"Your points: {S.balance(status)}  ·  earned in total: {S.earned(status)}")
        self._clear_body()
        if not self._items:
            self.body_lay.addWidget(self._note("The price list could not be loaded."))
            self._grow_to_content()
            return
        # the skill levels are free now - the Shop sells animals only
        self._add_animals(status)
        need = S.points_to_cheapest(self._items, status)
        if need:
            self.body_lay.addWidget(self._note(
                f"You cannot afford anything yet - the cheapest item needs "
                f"{_points(need)} more."))
        self.body_lay.addStretch(1)
        self._grow_to_content()

    def _section(self, title):
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 14px; font-weight: 700;")
        self.body_lay.addWidget(lbl)

    def _add_animals(self, status):
        self._section("Animals for the live discharge plot")
        for_sale = S.animals_for_sale(self._items, status)
        row = QHBoxLayout()
        self.cmb_animal = QComboBox()
        self.cmb_animal.setIconSize(QSize(32, 32))
        for item in for_sale:
            text = f"{item['name']} - {_points(int(item['price']))}"
            icon = _icon(item["code"])
            if icon is not None:
                self.cmb_animal.addItem(icon, text, item["code"])
            else:
                self.cmb_animal.addItem(f"{_emoji(item['code'])}  {text}".strip(),
                                        item["code"])
        self.btn_animal = QPushButton("Buy")
        self.btn_animal.setAutoDefault(False)
        self.btn_animal.clicked.connect(self._buy_selected_animal)
        if not for_sale:
            self.cmb_animal.addItem("No animal you can afford right now", None)
            self.cmb_animal.setEnabled(False)
            self.btn_animal.setEnabled(False)
        row.addWidget(self.cmb_animal, 1)
        row.addWidget(self.btn_animal)
        self.body_lay.addLayout(row)
        mine = S.owned(status)
        owned = [i for i in self._items if i.get("kind") == "animal" and i["code"] in mine
                 and i["code"] not in S.FREE_ANIMALS]
        self.body_lay.addWidget(self._note(
            "Trout and Bottle are free for everyone - choose them in Preferences ▸ "
            "Display ▸ Select animal."))
        if owned:
            names = ", ".join(f"{_emoji(i['code'])} {i['name']}".strip() for i in owned)
            self.body_lay.addWidget(self._note(
                f"✓ bought: {names} - choose one in Preferences ▸ Display ▸ "
                "Select animal"))

    # ---- buying ----------------------------------------------------------------------
    def _buy_selected_animal(self):
        code = self.cmb_animal.currentData()
        item = next((i for i in self._items if i["code"] == code), None)
        if item is not None:
            self._buy(item)

    def _buy(self, item):
        price = int(item["price"])
        after = S.balance(self._status()) - price
        answer = QMessageBox.question(
            self, "CWatM Shop",
            f"Buy {item['name']} for {_points(price)}?\n\n"
            f"Your points afterwards: {after}. Your badges stay.\n"
            "Purchases are final - there are no refunds.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._bought_item = item
            self._run("buy", item["code"])

    def _after_buy(self, result):
        """The main window has taken the new status over already (``buy`` is one of
        its status operations) - redraw, then put the purchase to use."""
        item = getattr(self, "_bought_item", None) or {}
        self._fill()
        self._say(f"Bought: {item.get('name', result.get('item'))}.", "ok_color")
        code = item.get("code")
        if code in _ANIMAL_NAMES:
            # bought to be seen: it becomes the sparkline's animal
            try:
                self.mw._set_animal(_ANIMAL_NAMES[code])
            except Exception:
                log.debug("could not select the bought animal", exc_info=True)


def open_shop(mw):
    return _open_single(mw, "_shop_window", ShopWindow)
