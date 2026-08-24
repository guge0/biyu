from __future__ import annotations

import os

import pytest

from tests.support.viewport_contracts import VIEWPORT_ASSERTIONS_JS


pytestmark = pytest.mark.e2e


def _visible_text_is_not_clipped(page) -> bool:
    return page.evaluate(
        """() => [...document.querySelectorAll('body *:not(.sr-only)')]
          .filter(el => el.children.length === 0 && el.textContent.trim())
          .filter(el => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              rect.width > 1 && rect.height > 1;
          })
          .every(el => el.scrollWidth <= el.clientWidth + 1)"""
    )


def test_workbench_viewport_contracts(page) -> None:
    base = os.environ["BIYU_QA_BASE_URL"]
    book = os.environ.get("BIYU_QA_BOOK", "dev-1787149384")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base}/workbench.html?book={book}&chapter=1")
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.locator("#workbench-book-name").wait_for(state="visible")
    page.wait_for_function(
        "document.querySelector('#workbench-book-name').textContent !== '正在读取书名…'"
    )
    page.locator("#workbench-more-toggle").click()
    result = page.evaluate(
        """() => {{
          const rules = {checker};
          const menu = document.querySelector('#workbench-more-menu');
          return {{
            horizontal: rules.noHorizontalOverflow(),
            menu: menu ? rules.overlayWithinViewport(menu) : true,
            menuVisible: menu ? !menu.hidden : false,
            actionRow: ['load', 'stage-bar', 'workbench-more-toggle']
              .map(id => document.getElementById(id).getBoundingClientRect().top)
              .reduce((ok, top, _index, tops) => ok && Math.max(...tops) - Math.min(...tops) < 8, true),
            forbidden: ['中枢', '裁定', '读稿层', '工单号', '防手滑副本', '副本尚未设置', '备份']
              .filter(word => document.body.innerText.includes(word)),
          }};
        }}""".format(checker=VIEWPORT_ASSERTIONS_JS),
    )
    assert result == {
        "horizontal": True,
        "menu": True,
        "menuVisible": True,
        "actionRow": True,
        "forbidden": [],
    }
    assert _visible_text_is_not_clipped(page)


def test_inline_character_create_viewport_contracts(page) -> None:
    base = os.environ["BIYU_QA_BASE_URL"]
    book = os.environ.get("BIYU_QA_BOOK", "dev-1787149384")
    for width, height in ((1449, 1000), (1280, 800)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{base}/settings.html?book={book}")
        page.wait_for_load_state("networkidle", timeout=10_000)
        page.get_by_role("button", name="人物卡总览", exact=True).click()
        page.get_by_role("button", name="＋ 新建人物卡", exact=True).click()
        result = page.evaluate(
            """() => {
              const name = document.querySelector('[data-field="姓名"]');
              const title = document.querySelector('#cell-title');
              const labels = [...document.querySelectorAll('#character-editor .character-field > span')]
                .map(el => el.textContent);
              return {
                viewport: [innerWidth, innerHeight],
                horizontal: document.documentElement.scrollWidth <= innerWidth,
                floating: document.querySelectorAll('dialog, [role="dialog"]').length,
                titleVisible: title.getBoundingClientRect().bottom <= innerHeight,
                nameVisible: name.getBoundingClientRect().bottom <= innerHeight,
                errorUnderName: name.nextElementSibling?.hasAttribute('data-name-error') === true,
                labels,
              };
            }"""
        )
        assert result["viewport"] == [width, height]
        assert result["horizontal"] is True
        assert result["floating"] == 0
        assert result["titleVisible"] is True and result["nameVisible"] is True
        assert result["errorUnderName"] is True
        assert result["labels"] == [
            "姓名", "档位", "角色定位", "背景", "性格", "叙述者怎么称呼他",
            "他怎么自称", "别人怎么叫他", "正文里不许用的称呼", "语声样本",
        ]
        assert _visible_text_is_not_clipped(page)
