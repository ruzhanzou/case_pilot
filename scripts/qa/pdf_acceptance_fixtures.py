"""Create synthetic PDF evidence with the same dependencies as the worker."""
import sys
from pathlib import Path

import pymupdf


def create_fixtures(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((60, 75), 'Verification Code Login - Current Rules', fontsize=18)
        page.insert_text((60, 120), '\n'.join([
            'R1: A verification code expires 300 seconds after it is issued.',
            'An expired verification code must fail login with error E731.',
            'The test environment supports advancing the server clock.',
        ]), fontsize=12)
        document.save(destination / 'requirements.pdf')
        rendered = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        with pymupdf.open() as scan:
            scan_page = scan.new_page(width=page.rect.width, height=page.rect.height)
            scan_page.insert_image(scan_page.rect, stream=rendered.tobytes('png'))
            scan.save(destination / 'scan-only.pdf')
    with pymupdf.open() as empty:
        empty.new_page()
        empty.save(destination / 'empty.pdf')


def create_chinese_mixed(destination: Path):
    """History in native text, current rules scanned, plus a harmless blank page."""
    destination.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        for heading, rules in [
            ('验证码登录需求（历史版本，已作废）', [
                '以下规则已经作废，不得继续用于当前测试：',
                '验证码在签发后420秒过期。过期登录返回错误码OLD。',
            ]),
            ('验证码登录需求（当前生效版本）', [
                '以下是当前生效的规则，取代历史版本：',
                '验证码在签发后300秒过期。',
                '使用过期验证码登录必须失败，并返回错误码E731。',
                '测试环境支持推进服务器时钟以测试过期边界。',
            ]),
        ]:
            page=document.new_page()
            page.insert_text((50,75),heading,fontname='china-s',fontsize=18)
            page.insert_text((50,125),'\n'.join(rules),fontname='china-s',fontsize=14,lineheight=2)
        document.save(destination/'requirements.pdf')
        with pymupdf.open() as mixed:
            mixed.insert_pdf(document,from_page=0,to_page=0)
            page=mixed.new_page()
            raster=document[1].get_pixmap(matrix=pymupdf.Matrix(2,2))
            page.insert_image(page.rect,stream=raster.tobytes('png'))
            mixed.new_page()
            mixed.save(destination/'scan-only.pdf')
    with pymupdf.open() as empty:
        empty.new_page();empty.save(destination/'empty.pdf')


if __name__ == '__main__':
    (create_chinese_mixed if '--chinese-mixed' in sys.argv else create_fixtures)(Path(sys.argv[1]))
