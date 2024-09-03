from copy import deepcopy

from pypdf import PdfReader, PdfWriter


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


def save_pdf(writer):
    with open('pypdf-output.pdf', 'wb') as fp:
        writer.write(fp)


def main():
    reader = PdfReader('Asyncio.pdf')
    writer = process_pdf(reader)
    save_pdf(writer)


if __name__ == '__main__':
    main()
