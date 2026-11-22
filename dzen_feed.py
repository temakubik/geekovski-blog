"""HTML adapter for Dzen RSS (only the Python standard library)."""
import html
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class _Node:
    def __init__(self, tag="", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []


class _Tree(HTMLParser):
    def __init__(self, fragment):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(fragment)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "hr", "source", "input", "meta", "link"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def adapt_html(fragment, site_url, image_allowed):
    """Flatten tables, remove unsupported markup, retain text and source URLs.

    Dzen supports plain list items only. Links inside them become text + URL;
    outside lists links stay clickable. Images must pass a local size/format check.
    """
    drop = {"script", "style", "iframe", "object", "template"}
    allowed = {"p", "a", "b", "i", "u", "s", "h1", "h2", "h3", "h4",
               "blockquote", "ul", "ol", "li", "figure", "figcaption", "img"}
    aliases = {"strong": "b", "em": "i", "del": "s"}

    def url(value):
        value = (value or "").strip()
        if value.startswith("#"):
            return value
        value = urljoin(site_url + "/", value)
        return value if urlsplit(value).scheme in {"http", "https"} else ""

    def plain(node):
        if isinstance(node, str):
            return node
        if node.tag in drop:
            return ""
        text = "".join(plain(c) for c in node.children)
        if node.tag == "a":
            href = url(node.attrs.get("href"))
            if href and not href.startswith("#") and href != text.strip():
                text += " (%s)" % href
        return text

    def rows(node):
        for child in node.children:
            if isinstance(child, _Node):
                if child.tag == "tr":
                    yield child
                else:
                    yield from rows(child)

    def table(node):
        headers, out = [], []
        for row in rows(node):
            cells = [c for c in row.children if isinstance(c, _Node) and c.tag in {"th", "td"}]
            if not cells:
                continue
            if not headers and all(c.tag == "th" for c in cells):
                headers = [plain(c).strip() for c in cells]
                continue
            values = []
            for i, cell in enumerate(cells):
                label = "<b>%s:</b> " % html.escape(headers[i]) if i < len(headers) else ""
                values.append(label + "".join(render(c) for c in cell.children))
            out.append("<p>%s</p>" % "; ".join(values))
        if not out and headers:
            out.append("<p>%s</p>" % "; ".join(html.escape(h) for h in headers))
        return "\n".join(out)

    def render(node):
        if isinstance(node, str):
            return html.escape(node)
        if node.tag in drop:
            return ""
        if node.tag == "table":
            return table(node)
        if node.tag == "li":
            return "<li>%s</li>" % html.escape(plain(node).strip())
        if node.tag == "br":
            return " "
        tag = aliases.get(node.tag, node.tag)
        content = "".join(render(c) for c in node.children)
        if tag not in allowed:
            return content
        attrs = ""
        if tag == "img":
            src = url(node.attrs.get("src"))
            if not src or not image_allowed(src):
                return ""
            return '<img src="%s" alt="%s">' % (
                html.escape(src, quote=True), html.escape(node.attrs.get("alt", ""), quote=True))
        if tag == "a":
            href = url(node.attrs.get("href"))
            if not href:
                return content
            attrs = ' href="%s"' % html.escape(href, quote=True)
        if tag in {"h2", "h3", "h4"} and node.attrs.get("id"):
            attrs = ' id="%s"' % html.escape(node.attrs["id"], quote=True)
        if tag == "figure" and "<img " not in content:
            return ""
        return "<%s%s>%s</%s>" % (tag, attrs, content, tag)

    return render(_Tree(fragment).root)
