"""Zero-dependency native Windows SpellChecker COM service (en-AU / system dictionaries)."""
from __future__ import annotations

from collections import OrderedDict
import ctypes
from ctypes import wintypes
import os
import re
import threading
from typing import Any


WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

_BUILTIN_DOMAIN_ALLOWLIST: frozenset[str] = frozenset({
    "fairybread",
    "evidencebench",
    "deepseek",
    "deepgram",
    "openai",
    "cerebras",
    "cohere",
    "cartesia",
    "elevenlabs",
    "groq",
    "qwen",
    "mistral",
    "codestral",
    "ollama",
    "pyside",
    "jellyfin",
    "antigravity",
    "mempalace",
    "autopatch",
    "sqlite",
    "fts",
    "dpapi",
    "json",
    "jsonl",
    "svg",
    "png",
    "pcm",
    "wav",
    "tts",
    "stt",
    "mcp",
    "sdk",
    "cli",
    "gui",
    "api",
    "url",
    "http",
    "https",
    "localhost",
    "palace",
    "idle",
    "synth",
    "sienna",
    "thalia",
    "hyperion",
    "orpheus",
})


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_str(cls, raw: str) -> "_GUID":
        parts = raw.strip("{}").split("-")
        tail = bytes.fromhex(parts[3] + parts[4])
        return cls(
            int(parts[0], 16),
            int(parts[1], 16),
            int(parts[2], 16),
            (ctypes.c_ubyte * 8)(*tail),
        )


def _in_inline_backticks(text: str, pos: int) -> bool:
    before = text.count("`", 0, pos)
    if before % 2 == 1 and "`" in text[pos:]:
        return True
    return False


def should_skip_word(word: str, full_text: str, start: int, end: int) -> bool:
    """Return True for technical tokens, commands, mentions, paths, URLs, acronyms, and domain words."""
    if not word or len(word) < 2:
        return True
    if word.isupper() and len(word) >= 2:
        return True
    # camelCase or PascalCase identifier (e.g., PalaceWindow, setSizeHint)
    if any(ch.isupper() for ch in word[1:]):
        return True
    low = word.lower()
    if low in _BUILTIN_DOMAIN_ALLOWLIST:
        return True

    n = len(full_text)
    if start > 0:
        prev_ch = full_text[start - 1]
        if prev_ch in "_/\\@" or prev_ch.isdigit():
            return True
        if prev_ch == "." and start >= 2 and (full_text[start - 2].isalnum() or full_text[start - 2] in "/\\"):
            return True
    if end < n:
        next_ch = full_text[end]
        if next_ch in "_/\\@:" or next_ch.isdigit():
            return True
        if next_ch == "." and (end + 1) < n and full_text[end + 1].isalnum():
            return True
    if _in_inline_backticks(full_text, start):
        return True
    return False


class WindowsSpellChecker:
    """Thread-safe wrapper over Windows MsSpellCheckingFacility COM (ISpellCheckerFactory/ISpellChecker)."""

    _PREFERRED_LANGS = ("en-AU", "en-US", "en-GB")
    _MAX_CACHE = 2048

    def __init__(self, preferred_langs: tuple[str, ...] | None = None):
        self._preferred_langs = tuple(preferred_langs or self._PREFERRED_LANGS)
        self._lock = threading.RLock()
        self._initialized = False
        self._available = False
        self._language = ""
        self._ole32: Any = None
        self._factory: ctypes.c_void_p | None = None
        self._checker: ctypes.c_void_p | None = None
        self._fn_check: Any = None
        self._fn_suggest: Any = None
        self._fn_add: Any = None
        self._fn_ignore: Any = None
        self._fn_release: Any = None
        self._word_cache: OrderedDict[str, bool] = OrderedDict()
        self._ignored: set[str] = set()

    @staticmethod
    def _vtbl(com_ptr: ctypes.c_void_p):
        return ctypes.cast(
            ctypes.cast(com_ptr, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )

    def _release_ptr(self, com_ptr: ctypes.c_void_p | None) -> None:
        if com_ptr is None or not getattr(com_ptr, "value", None):
            return
        try:
            vt = self._vtbl(com_ptr)
            rel = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
            rel(com_ptr)
        except Exception:
            pass

    def _ensure_init(self) -> bool:
        with self._lock:
            if self._initialized:
                return self._available
            self._initialized = True
            if os.name != "nt":
                return False
            try:
                ole32 = ctypes.windll.ole32
                hr_co = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
                # Accept S_OK (0), S_FALSE (1), or RPC_E_CHANGED_MODE (0x80010106)
                if (hr_co & 0xFFFFFFFF) not in (0, 1, 0x80010106):
                    return False

                clsid = _GUID.from_str("{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}")
                iid = _GUID.from_str("{8E018A9D-2415-4677-BF08-794EA61F94BB}")
                factory = ctypes.c_void_p()
                hr = ole32.CoCreateInstance(
                    ctypes.byref(clsid),
                    None,
                    1,  # CLSCTX_INPROC_SERVER
                    ctypes.byref(iid),
                    ctypes.byref(factory),
                )
                if hr != 0 or not factory.value:
                    return False

                fvtbl = self._vtbl(factory)
                is_sup = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(wintypes.BOOL)
                )(fvtbl[4])
                create_chk = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
                )(fvtbl[5])

                checker = ctypes.c_void_p()
                chosen_lang = ""
                for lang in self._preferred_langs:
                    sup = wintypes.BOOL(0)
                    if is_sup(factory, lang, ctypes.byref(sup)) == 0 and sup.value:
                        tmp_chk = ctypes.c_void_p()
                        if create_chk(factory, lang, ctypes.byref(tmp_chk)) == 0 and tmp_chk.value:
                            checker = tmp_chk
                            chosen_lang = lang
                            break

                if not checker.value:
                    self._release_ptr(factory)
                    return False

                cvtbl = self._vtbl(checker)
                self._ole32 = ole32
                self._factory = factory
                self._checker = checker
                self._language = chosen_lang
                self._fn_check = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
                )(cvtbl[4])
                self._fn_suggest = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
                )(cvtbl[5])
                self._fn_add = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p
                )(cvtbl[6])
                self._fn_ignore = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p
                )(cvtbl[7])
                self._available = True
                return True
            except Exception:
                self._available = False
                return False

    @property
    def available(self) -> bool:
        return self._ensure_init()

    @property
    def language(self) -> str:
        self._ensure_init()
        return self._language

    def _cache_put(self, key: str, value: bool) -> None:
        self._word_cache[key] = value
        self._word_cache.move_to_end(key)
        if len(self._word_cache) > self._MAX_CACHE:
            self._word_cache.popitem(last=False)

    def is_word_correct(self, word: str) -> bool:
        clean = (word or "").strip()
        if not clean or len(clean) < 2:
            return True
        low = clean.lower()
        if low in _BUILTIN_DOMAIN_ALLOWLIST or low in self._ignored:
            return True
        with self._lock:
            cached = self._word_cache.get(clean)
            if cached is not None:
                self._word_cache.move_to_end(clean)
                return cached
            if not self._ensure_init() or self._checker is None or self._fn_check is None:
                return True

            enum_err = ctypes.c_void_p()
            try:
                hr = self._fn_check(self._checker, clean, ctypes.byref(enum_err))
                if hr != 0 or not enum_err.value:
                    return True
                evtbl = self._vtbl(enum_err)
                err_next = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
                )(evtbl[3])
                err_ptr = ctypes.c_void_p()
                hr_n = err_next(enum_err, ctypes.byref(err_ptr))
                if hr_n == 0 and err_ptr.value:
                    self._release_ptr(err_ptr)
                    self._cache_put(clean, False)
                    return False
                self._cache_put(clean, True)
                return True
            except Exception:
                return True
            finally:
                self._release_ptr(enum_err)

    def find_misspelled_spans(
        self,
        text: str,
        *,
        skip_cursor_col: int | None = None,
    ) -> list[tuple[int, int, str]]:
        """Return [(start, length, word), ...] for misspelled tokens in text."""
        if not text or not self._ensure_init():
            return []
        spans: list[tuple[int, int, str]] = []
        for match in WORD_RE.finditer(text):
            st, end = match.start(), match.end()
            if skip_cursor_col is not None and st <= skip_cursor_col <= end:
                continue
            word = match.group(0)
            if should_skip_word(word, text, st, end):
                continue
            if not self.is_word_correct(word):
                spans.append((st, end - st, word))
        return spans

    def suggest(self, word: str, max_suggestions: int = 5) -> list[str]:
        clean = (word or "").strip()
        if not clean or max_suggestions <= 0:
            return []
        with self._lock:
            if not self._ensure_init() or self._checker is None or self._fn_suggest is None or self._ole32 is None:
                return []
            enum_str = ctypes.c_void_p()
            out: list[str] = []
            try:
                hr = self._fn_suggest(self._checker, clean, ctypes.byref(enum_str))
                if hr != 0 or not enum_str.value:
                    return []
                svtbl = self._vtbl(enum_str)
                str_next = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.POINTER(ctypes.c_wchar_p),
                    ctypes.POINTER(ctypes.c_ulong),
                )(svtbl[3])
                for _ in range(int(max_suggestions)):
                    wptr = ctypes.c_wchar_p()
                    got = ctypes.c_ulong(0)
                    if str_next(enum_str, 1, ctypes.byref(wptr), ctypes.byref(got)) == 0 and got.value == 1:
                        if wptr.value:
                            out.append(str(wptr.value))
                        self._ole32.CoTaskMemFree(wptr)
                    else:
                        break
                return out
            except Exception:
                return []
            finally:
                self._release_ptr(enum_str)

    def add_to_dictionary(self, word: str) -> bool:
        clean = (word or "").strip()
        if not clean:
            return False
        with self._lock:
            if not self._ensure_init() or self._checker is None or self._fn_add is None:
                return False
            try:
                ok = (self._fn_add(self._checker, clean) == 0)
            except Exception:
                ok = False
            if ok:
                self._ignored.add(clean.lower())
                for k in list(self._word_cache.keys()):
                    if k.lower() == clean.lower():
                        self._word_cache[k] = True
                self._cache_put(clean, True)
            return ok

    def ignore_word(self, word: str) -> bool:
        clean = (word or "").strip()
        if not clean:
            return False
        with self._lock:
            self._ignored.add(clean.lower())
            for k in list(self._word_cache.keys()):
                if k.lower() == clean.lower():
                    self._word_cache[k] = True
            self._cache_put(clean, True)
            if not self._ensure_init() or self._checker is None or self._fn_ignore is None:
                return True
            try:
                return self._fn_ignore(self._checker, clean) == 0
            except Exception:
                return True

    def close(self) -> None:
        with self._lock:
            self._release_ptr(self._checker)
            self._release_ptr(self._factory)
            self._checker = None
            self._factory = None
            self._available = False
            self._initialized = False


_GLOBAL_SPELLCHECKER_LOCK = threading.Lock()
_GLOBAL_SPELLCHECKER: WindowsSpellChecker | None = None


def get_spellchecker() -> WindowsSpellChecker:
    """Return the shared process-wide WindowsSpellChecker instance."""
    global _GLOBAL_SPELLCHECKER
    with _GLOBAL_SPELLCHECKER_LOCK:
        if _GLOBAL_SPELLCHECKER is None:
            _GLOBAL_SPELLCHECKER = WindowsSpellChecker()
        return _GLOBAL_SPELLCHECKER
