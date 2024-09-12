from copy import deepcopy
import io
from typing import Optional, Literal

from pypdf import PdfReader, PdfWriter, PageObject


def crop_page_to_separate_strongly(page):
    # horizontal
    mb = page.mediabox
    upper_page = deepcopy(page)
    down_page = deepcopy(page)

    upper_page.mediabox.upper_left = (0, mb.top)
    upper_page.mediabox.upper_right = (mb.right, mb.top)
    upper_page.mediabox.lower_left = (0, mb.top/2)
    upper_page.mediabox.lower_right = (mb.right, mb.top/2)

    down_page.mediabox.upper_left = (0, mb.top/2)
    down_page.mediabox.upper_right = (mb.right, mb.top/2)
    down_page.mediabox.lower_left = (0, 0)
    down_page.mediabox.lower_right = (mb.right, 0)

    return upper_page, down_page


def crop_page_to_separate_with_reserve(page):
    mb = page.mediabox
    upper_page = deepcopy(page)
    down_page = deepcopy(page)

    upper_page.mediabox.upper_left = (0, mb.top)
    upper_page.mediabox.upper_right = (mb.right, mb.top)
    upper_page.mediabox.lower_left = (0, mb.top/2 - mb.top*0.05)
    upper_page.mediabox.lower_right = (mb.right, mb.top/2 - mb.top*0.05)

    down_page.mediabox.upper_left = (0, mb.top/2 + mb.top*0.05)
    down_page.mediabox.upper_right = (mb.right, mb.top/2 + mb.top*0.05)
    down_page.mediabox.lower_left = (0, 0)
    down_page.mediabox.lower_right = (mb.right, 0)

    return upper_page, down_page


def process_pdf(reader):
    writer = PdfWriter()
    pages_count = len(reader.pages)
    for page_num, page in enumerate(reader.pages):
        print(f'Processed pages: {page_num}/{pages_count}')
        upper_page, down_page = crop_page_to_separate_with_reserve(page)
        upper_page = upper_page.rotate(-90)
        down_page = down_page.rotate(-90)
        writer.add_page(upper_page)
        writer.add_page(down_page)
    return writer


def separate_page_horizontally(page: PageObject, reserve: float):
    mb = page.mediabox
    upper_page = deepcopy(page)
    down_page = deepcopy(page)

    top = mb.top
    right = mb.right

    upper_page.mediabox.upper_left = (0, top)
    upper_page.mediabox.upper_right = (right, top)
    upper_page.mediabox.lower_left = (0, top/2 - top*reserve)
    upper_page.mediabox.lower_right = (right, top/2 - top*reserve)

    down_page.mediabox.upper_left = (0, top/2 + top*reserve)
    down_page.mediabox.upper_right = (right, top/2 + top*reserve)
    down_page.mediabox.lower_left = (0, 0)
    down_page.mediabox.lower_right = (right, 0)

    return upper_page, down_page


def separate_page_vertically(page: PageObject, reserve: float):
    mb = page.mediabox
    left_page = deepcopy(page)
    right_page = deepcopy(page)

    top = mb.top
    right = mb.right

    left_page.mediabox.upper_left = (0, top)
    left_page.mediabox.upper_right = (right/2 + right*reserve, top)
    left_page.mediabox.lower_left = (0, 0)
    left_page.mediabox.lower_right = (right/2 + right*reserve, 0)

    right_page.mediabox.upper_left = (right/2 - right*reserve, top)
    right_page.mediabox.upper_right = (right, top)
    right_page.mediabox.lower_left = (right/2 - right*reserve, 0)
    right_page.mediabox.lower_right = (right, 0)

    return left_page, right_page


def save_pdf(writer: PdfWriter):
    with open('pypdf-output.pdf', 'wb') as fp:
        writer.write(fp)


def separate_pdf(
    pdf_file_location: str, separate_strongly: bool,
    separate_orientation: Literal['horizontal', 'vertical'],
    reserve_percent: Optional[float]
):
    if separate_strongly:
        reserve = 0
    else:
        reserve = 0.01 * reserve_percent

    reader = PdfReader(pdf_file_location)
    writer = PdfWriter()

    pages_count = len(reader.pages)
    for page_num, page in enumerate(reader.pages):
        print(f'Processed pages: {page_num}/{pages_count}')
        if separate_orientation == 'horizontal':
            first_page, second_page = separate_page_horizontally(page, reserve)
        else:
            first_page, second_page = separate_page_vertically(page, reserve)

        writer.add_page(first_page)
        writer.add_page(second_page)

    writer = process_pdf(reader)
    myio = io.BytesIO()
    writer.write(myio)
    myio.seek(0)
    return myio


def rotate_pdf(
    pdf_file_location: str,
    direction_of_rotation: Literal['counterclockwise', 'clockwise']
):
    if direction_of_rotation == 'counterclockwise':
        rotation = -90
    else:
        rotation = 90

    reader = PdfReader(pdf_file_location)
    writer = PdfWriter()

    pages_count = len(reader.pages)
    for page_num, page in enumerate(reader.pages):
        print(f'Processed pages: {page_num}/{pages_count}')
        new_page = page.rotate(rotation)
        writer.add_page(new_page)
    writer = process_pdf(reader)
    myio = io.BytesIO()
    writer.write(myio)
    myio.seek(0)
    return myio


def main():
    reader = PdfReader('Asyncio.pdf')
    writer = process_pdf(reader)
    save_pdf(writer)


if __name__ == '__main__':
    main()
