WORKBENCH_JS_SRC = 'src="/workbench.js?v=c2-1"'


def assert_workbench_js_src(html: str) -> None:
    assert WORKBENCH_JS_SRC in html
