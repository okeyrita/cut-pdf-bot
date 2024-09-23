from copy import deepcopy
from typing import Optional, Literal, Union
from io import BytesIO

from pypdf import PdfReader, PdfWriter, PageObject


def process_pdf(reader):
    writer = PdfWriter()
    pages_count = len(reader.pages)
    for page_num, page in enumerate(reader.pages):
        print(f'Processed pages: {page_num}/{pages_count}')
        upper_page, down_page = separate_page_horizontally(page, 0)
        upper_page = upper_page.rotate(-90)
        down_page = down_page.rotate(-90)
        writer.add_page(upper_page)
        writer.add_page(down_page)
    return writer


def separate_page_horizontally(page: PageObject, reserve: Union[float, int] = 0):
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
    pdf_file: BytesIO, separate_strongly: Literal['Строго', 'С запасом'],
    separate_orientation: Literal['Горизонтально', 'Вертикально'],
    reserve_percent: Optional[str]
):
    if separate_strongly == 'Строго':
        reserve = 0
    else:
        reserve = 0.01 * float(reserve_percent)

    reader = PdfReader(pdf_file)
    writer = PdfWriter()

    pages_count = len(reader.pages)
    for page_num, page in enumerate(reader.pages):
        print(f'Processed pages: {page_num}/{pages_count}')
        if separate_orientation == 'Горизонтально':
            first_page, second_page = separate_page_horizontally(page, reserve)
        else:
            first_page, second_page = separate_page_vertically(page, reserve)

        writer.add_page(first_page)
        writer.add_page(second_page)

    myio = BytesIO()
    writer.write(myio)
    myio.seek(0)
    return myio


def rotate_pdf(
    pdf_file: BytesIO,
    direction_of_rotation: Literal['По часововй стрелке', 'Против часовой стрелки']
) -> BytesIO:
    if direction_of_rotation == 'Против часовой стрелки':
        rotation = -90
    else:
        rotation = 90

    reader = PdfReader(pdf_file)
    writer = PdfWriter()

    pages_count = len(reader.pages)
    for page_num, page in enumerate(reader.pages):
        print(f'Processed pages: {page_num}/{pages_count}')
        new_page = page.rotate(rotation)
        writer.add_page(new_page)
    myio = BytesIO()
    writer.write(myio)
    myio.seek(0)
    return myio


def main():
    reader = PdfReader('Asyncio.pdf')
    writer = process_pdf(reader)
    save_pdf(writer)


if __name__ == '__main__':
    main()
