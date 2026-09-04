"""Every user-facing string, in one place.

Nothing outside this module contains Russian text. Handlers reference these constants and
the :func:`label` helper; the domain layer never sees them. Swapping in a real i18n backend means
replacing this module, not hunting through handlers.
"""

from collections.abc import Mapping
from enum import StrEnum

from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    NavAction,
    OcrLang,
    Operation,
    Orientation,
    RotateDirection,
    SplitMode,
)


# Button captions, grouped per enum.
#
# These are deliberately NOT one flat dict. StrEnum members hash and compare as their string value,
# so `Orientation.HORIZONTAL` ("h") and `NavAction.HOME` ("h") are the *same* dict key and one
# silently overwrites the other. Grouping by enum type makes collisions impossible, since @unique
# already guarantees values are distinct within a single enum.
_LABELS: Mapping[type[StrEnum], Mapping[StrEnum, str]] = {
    Operation: {
        Operation.SPLIT: "✂️ Разделить страницы",
        Operation.ROTATE: "🔄 Повернуть страницы",
        Operation.MERGE: "📎 Объединить файлы",
        Operation.COMPRESS: "🗜 Сжать PDF",
        Operation.OCR: "🔍 Распознать текст (OCR)",
        Operation.EXTRACT: "📄 Извлечь текст",
    },
    Orientation: {
        Orientation.HORIZONTAL: "Горизонтально",
        Orientation.VERTICAL: "Вертикально",
    },
    SplitMode: {
        SplitMode.STRICT: "Строго пополам",
        SplitMode.RESERVE: "С запасом",
    },
    RotateDirection: {
        RotateDirection.CW: "По часовой стрелке",
        RotateDirection.CCW: "Против часовой стрелки",
    },
    CompressLevel: {
        CompressLevel.LOSSLESS: "Без потерь",
        CompressLevel.EBOOK: "Для чтения (среднее)",
        CompressLevel.SCREEN: "Максимальное (хуже качество)",
    },
    OcrLang: {
        OcrLang.RUS: "Русский",
        OcrLang.ENG: "Английский",
        OcrLang.RUS_ENG: "Русский + английский",
    },
    ExportFormat: {
        ExportFormat.TXT: "TXT",
        ExportFormat.EPUB: "EPUB",
    },
    NavAction: {
        NavAction.CANCEL: "❌ Отмена",
        NavAction.BACK: "◀️ Назад",
        NavAction.HOME: "🏠 В начало",
        NavAction.MERGE_DONE: "✅ Готово, объединить",
    },
}


def label(member: StrEnum) -> str:
    """Russian caption for an enum member.

    Raises:
        KeyError: if the enum or member has no caption -- caught by
            ``tests/unit/test_texts.py``, which asserts every member of every labelled enum is
            covered, so a newly added variant fails the suite instead of the bot.
    """
    return _LABELS[type(member)][member]


# --------------------------------------------------------------------------- screens

START = (
    "Привет, {name}!\n\n"
    "Я помогу подготовить PDF-книгу для чтения на телефоне или электронной книге: "
    "разрежу развороты, поверну страницы, объединю или сожму файлы, "
    "распознаю текст и вытащу его в TXT или EPUB.\n\n"
    "Выберите операцию:"
)

HELP = (
    "<b>Что я умею</b>\n\n"
    "✂️ <b>Разделить страницы</b> — режет каждую страницу пополам по горизонтали или вертикали. "
    "Удобно для книг, свёрстанных разворотами. Можно резать строго посередине или «с запасом», "
    "чтобы строки на стыке не обрезались.\n\n"
    "🔄 <b>Повернуть страницы</b> — поворот всех страниц на 90° в любую сторону.\n\n"
    "📎 <b>Объединить файлы</b> — склеивает несколько PDF в один, в порядке отправки.\n\n"
    "🗜 <b>Сжать PDF</b> — уменьшает размер файла. «Без потерь» не трогает картинки, "
    "остальные режимы пережимают изображения.\n\n"
    "🔍 <b>OCR</b> — распознаёт текст на отсканированных страницах и добавляет текстовый слой, "
    "после чего по книге можно искать и копировать текст.\n\n"
    "📄 <b>Извлечь текст</b> — выгружает текст книги в TXT или EPUB. "
    "Для сканов сначала нужен OCR.\n\n"
    "<b>Команды</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/cancel — отменить текущую операцию в любой момент\n\n"
    "<b>Ограничения</b>\n"
    "Файл до {max_size} МБ, до {max_pages} страниц, "
    "до {max_merge} файлов за одно объединение."
)

CHOOSE_OPERATION = "Выберите операцию:"
ASK_ORIENTATION = "Как разрезать страницы?"
ASK_SPLIT_MODE = "Резать строго пополам или с запасом?"
ASK_RESERVE = (
    "Введите размер запаса в процентах — число от 0 до 100.\n"
    "Например: <code>5</code> или <code>7.5</code>.\n\n"
    "Каждая половина будет продлена за середину страницы на этот процент, "
    "чтобы строки на стыке не обрезались."
)
ASK_ROTATE_DIRECTION = "В какую сторону повернуть страницы?"
ASK_COMPRESS_LEVEL = "Насколько сильно сжимать?"
ASK_OCR_LANG = "На каком языке текст в книге?"
ASK_EXPORT_FORMAT = "В какой формат выгрузить текст?"

SEND_FILE = "Пришлите PDF-файл."
SEND_FILES_TO_MERGE = (
    "Присылайте PDF-файлы по одному — я склею их в порядке отправки.\n"
    "Когда закончите, нажмите «Готово»."
)
MERGE_COLLECTED = (
    "Принято файлов: <b>{count}</b> (страниц: {pages}).\nПрисылайте ещё или нажмите «Готово»."
)
ERR_NEED_MORE_FILES = "Нужно минимум 2 файла — пришлите ещё хотя бы один."

QUEUED = "⏳ Файл принят, поставлен в очередь…"
PROGRESS = "{bar} {done}/{total} стр."
PROGRESS_STAGE = "{bar} {stage}"
DONE = "✅ Готово!"
CANCELLED = "🚫 Операция отменена."
NOTHING_TO_CANCEL = "Сейчас нечего отменять. /start — главное меню."

# --------------------------------------------------------------------------- stages

STAGE_COMPRESSING = "Сжимаю…"
STAGE_OCR = "Распознаю текст…"
STAGE_BUILDING = "Собираю файл…"

# --------------------------------------------------------------------------- errors

ERR_NOT_A_PDF = "❌ Это не PDF. Пришлите файл с расширением .pdf."
ERR_BROKEN_PDF = (
    "❌ Не получилось прочитать этот PDF — файл повреждён или имеет нестандартный формат."
)
ERR_ENCRYPTED = "❌ PDF защищён паролем. Снимите защиту и пришлите файл заново."
ERR_TOO_LARGE = "❌ Файл слишком большой: {size} МБ при лимите {limit} МБ."
ERR_TOO_MANY_PAGES = "❌ В файле {pages} страниц при лимите {limit}."
ERR_TOO_MANY_FILES = "❌ Больше {limit} файлов за раз объединить не получится."
ERR_NO_TEXT_LAYER = (
    "❌ В этом PDF нет текстового слоя — похоже, это скан.\n"
    "Сначала прогоните файл через 🔍 OCR, потом извлекайте текст."
)
ERR_BAD_RESERVE = "❌ Нужно число от 0 до 100. Попробуйте ещё раз, например: <code>5</code>."
ERR_BUSY = "⏳ Ваш предыдущий файл ещё обрабатывается. Дождитесь результата или нажмите /cancel."
ERR_PROCESSING_FAILED = (
    "❌ Не удалось обработать файл. Попробуйте ещё раз или пришлите другой PDF."
)
ERR_TIMEOUT = "❌ Обработка заняла слишком много времени и была прервана."
ERR_UNEXPECTED = "❌ Что-то пошло не так. Я уже записал ошибку в лог — попробуйте ещё раз."
ERR_SEND_FILE_PLEASE = "Пришлите PDF-файл документом (не фотографией и не архивом)."

# --------------------------------------------------------------------------- results

RESULT_COMPRESSED = "Было: {before} МБ → стало: {after} МБ (−{percent}%)."
RESULT_COMPRESS_NO_GAIN = (
    "Сжать заметно не получилось — файл уже хорошо упакован. Возвращаю исходник без изменений."
)
RESULT_OCR = "Распознано страниц: {pages}. Теперь по книге можно искать текст."
RESULT_SPLIT = "Страниц было: {before}, стало: {after}."
