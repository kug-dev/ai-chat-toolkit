"""Shared constants, standard-library imports, and data models."""
from __future__ import annotations

import argparse

import csv

import hashlib

import html

import json

import math

import os

import queue

import re

import sqlite3

import sys

import threading

import time

import unicodedata

import urllib.error

import urllib.request

import webbrowser

import zipfile

from collections import Counter, defaultdict, deque

from dataclasses import dataclass, field

from datetime import datetime

from pathlib import Path

from typing import Callable, Iterable

APP_NAME = "Chat Topic Finder"

VERSION = "2.3.0"

MAX_TEXT_CHARS = 1_500_000

MAX_CANDIDATE_PAIRS = 2_000_000

REPORT_PAIR_FLOOR = 0.10

MAX_INTERACTIVE_EDGES = 6_000

DEFAULT_LLM_URL = "http://localhost:11434"

DEFAULT_LLM_PROVIDER = "auto"

DEFAULT_LLM_MAX_CHARS = 28_000

STOPWORDS = set((
    "a an the and or but if then else when while where what which who whom whose why how "
    "is am are was were be been being do does did have has had having can could will would "
    "shall should may might must not no yes of to in on at by for from with about as into "
    "over under again further once here there all any both each few more most other some such "
    "only own same so than too very s t just don now i me my we our you your he she it they "
    "them their this that these those im ive id ill youre youve youll hes shes its theyre "
    "thats theres cant couldnt didnt doesnt dont hadnt hasnt havent isnt mightnt mustnt neednt "
    "shant shouldnt wasnt werent wont wouldnt user assistant system tool image video audio file "
    "ה את של על עם זה זו זאת הוא היא הם הן אני אנחנו אתם אתן אשר אם או גם לא כן כי אבל היה היתה "
    "היו להיות יש אין כל כבר עוד רק איך מה מי למה כאשר כמו בין מן על אל עם לו לה להם להן שלי שלך שלו "
    "שלה שלנו שלכם שלהן זאת אלה זה כאן שם עבור מתוך לגבי כדי מאוד יותר פחות אולי אפשר צריך רוצה רוצה לי לך "
).split())

CODE_STOPWORDS = set((
    "def class return import from as pass break continue lambda yield async await try except "
    "finally raise with assert del global nonlocal True False None self cls init main "
    "function const let var new this super extends implements interface type enum export default "
    "public private protected static final void int float double char boolean string bool "
    "struct impl fn pub mut use mod crate match Some Ok Err vec println format "
    "div span p a ul li ol table tr td th thead tbody form input button select option label "
    "style script head body html meta link title section header footer nav main article aside "
    "width height margin padding border display flex grid color background font align center "
    "select where insert into update delete join left right inner outer group order by having limit "
    "null true false undefined nan inf console log print printf fmt err error res req ctx "
).casefold().split())

TOKEN_RE = re.compile(r"(?u)[^\W_]+(?:['’ʼ-][^\W_]+)*")

CODE_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,45}")

ROLE_RE = re.compile(r"^\s*##\s*(user|assistant|system|tool|human|model)\b(?:[ \t]*[—-][ \t]*([^\n]+))?.*$", re.I)

MEDIA_URL_RE = re.compile(r"https?://\S+", re.I)

CODE_BLOCK_RE = re.compile(r"```([\w+#.-]*)\s*\n([\s\S]*?)```")

HEBREW_CHAR_RE = re.compile(r"[\u0590-\u05FF]")

DATE_ISO_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

HEBREW_FINAL_MAP = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})

HEBREW_DOUBLE_PREFIXES = ("מה", "שה", "וב", "ול", "וכ", "ומ", "וש", "בה", "לה", "כה")

HEBREW_SINGLE_PREFIXES = ("ו", "ה", "ב", "כ", "ל", "מ", "ש")

HEBREW_SUFFIXES = ("תיים", "יות", "ים", "ות", "יי", "ען", "ת")

@dataclass
class Chat:
    title: str
    text: str
    user_text: str
    assistant_text: str
    source: str
    archive: str = ""
    member: str = ""
    digest: str = ""
    truncated: bool = False
    chat_date: str = ""
    site: str = ""
    project_tag: str = ""
    model_slug: str = ""
    conv_id: str = ""
    code_text: str = ""
    code_langs: list[str] = field(default_factory=list)
    artifact_text: str = ""
    artifact_names: list[str] = field(default_factory=list)
    llm_report: dict = field(default_factory=dict)
    tokens: list[str] = field(default_factory=list)
    features: Counter = field(default_factory=Counter)
    vector: dict[str, float] = field(default_factory=dict)
    group_id: str = ""
    turns: list[dict[str, str]] = field(default_factory=list)
    generated_media_only: bool = False
    generated_media_count: int = 0

@dataclass
class TopicGroup:
    id: str
    members: list[int]
    parent_id: int | None = None
    subclustered: bool = False
    effective_threshold: float = 0.0

@dataclass
class ArchiveHealth:
    archive: str
    zip_status: str = "not checked"
    manifest_chats: int = 0
    chat_markdown_files: int = 0
    raw_json_fallbacks: int = 0
    files_saved: int = 0
    files_missing: int = 0
    files_skipped: int = 0
    manifest_errors: int = 0
    notes: str = ""
