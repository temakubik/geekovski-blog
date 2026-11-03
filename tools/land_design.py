#!/usr/bin/env python3
"""Лендит дизайн-правки из воркспейса Onlook Studio в main.

Onlook держит свою ветку в отдельном ворктри
(~/Library/Application Support/Onlook Studio/workspaces/github-com-temakubik-geekovski-blog/<ветка>)
и пушит туда коммиты дизайна. Скрипт находит этот ворктри, сливает его ветку
с origin/main во временном ворктри, пересобирает docs/ и проверяет вывод.
Коммитит и пушит (то есть деплоит сайт) только с явным --push.

  python3 tools/land_design.py               # посмотреть, что приедет (ничего не меняет)
  python3 tools/land_design.py --push        # влить в main и задеплоить
  python3 tools/land_design.py --branch X    # взять не Onlook-ветку, а указанную
  python3 tools/land_design.py --theme magazine --push
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ONLOOK_MARK = "Onlook Studio"
CONFLICT_SIDE = "origin/main"


def git(*args, cwd=ROOT, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if check and p.returncode:
        sys.exit("git %s → %d\n%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
    return p


def onlook_worktree():
    """Ворктри Onlook и ветка, которую он держит."""
    out = git("worktree", "list", "--porcelain").stdout
    entry = {}
    found = []
    for line in out.splitlines() + [""]:
        if not line.strip():
            if entry.get("worktree", "").find(ONLOOK_MARK) != -1:
                found.append(entry)
            entry = {}
            continue
        key, _, val = line.partition(" ")
        entry[key] = val
    if not found:
        sys.exit("Не нашёл ворктри Onlook Studio. Открой проект в Onlook или укажи --branch.")
    if len(found) > 1:
        print("Ворктри Onlook несколько, беру первый:")
        for f in found:
            print("  %s → %s" % (f["worktree"], f.get("branch", "?")))
    wt = found[0]
    branch = wt.get("branch", "").replace("refs/heads/", "")
    if not branch:
        sys.exit("Ворктри Onlook в detached HEAD — закоммить правки в ветку и повтори.")
    dirty = git("status", "--porcelain", cwd=wt["worktree"]).stdout.strip()
    if dirty:
        sys.exit("В ворктри Onlook есть незакоммиченные изменения — сохрани их в Onlook/закоммить:\n" + dirty)
    return wt["worktree"], branch


def placeholders_ok(paths):
    """Литеральные {placeholder} и маркеры конфликтов в собранных страницах."""
    bad = []
    pat = re.compile(r"\{[a-z_]{2,}\}|<<<<<<<|>>>>>>>")
    for f in paths:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                bad.append("%s:%d: %s" % (f.relative_to(ROOT.parent), i, line.strip()[:110]))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", help="ветка с правками (по умолчанию — из ворктри Onlook)")
    ap.add_argument("--theme", default="editorial", choices=["editorial", "dashboard", "magazine"])
    ap.add_argument("--push", action="store_true", help="закоммитить merge в main и запушить (деплой)")
    a = ap.parse_args()

    origin_main = git("rev-parse", "origin/main").stdout.strip()
    git("fetch", "origin", "--prune")

    if a.branch:
        branch, wt_path = a.branch, None
    else:
        wt_path, branch = onlook_worktree()

    src = "origin/%s" % branch
    git("rev-parse", "--verify", src)  # ветка должна быть на GitHub

    ahead = git("rev-list", "--count", "%s..%s" % (origin_main, src)).stdout.strip()
    if ahead == "0":
        print("В %s нет новых коммитов относительно origin/main — лендить нечего." % branch)
        return 0
    print("Новых коммитов в %s: %s" % (branch, ahead))
    log = git("log", "--oneline", "--no-decorate", "%s..%s" % (origin_main, src)).stdout.strip()
    print(log)

    scratch = Path(tempfile.mkdtemp(prefix="land-design-"))
    work = scratch / "repo"
    try:
        git("worktree", "add", "--detach", str(work), origin_main)
        m = git("merge", "--no-ff", "--no-commit", src, cwd=work, check=False)
        if m.returncode:
            conflicted = git("diff", "--name-only", "--diff-filter=U", cwd=work).stdout.split()
            git("merge", "--abort", cwd=work, check=False)
            print("\nКонфликт в %d файлах:" % len(conflicted))
            for f in conflicted:
                print("  " + f)
            print("\ndocs/*.html руками не мержим — это вывод build.py. Разреши конфликты в\n"
                  "build.py / static/ по правилам из скилла geekovski-blog, затем повтори:")
            print("  шпаргалка: оба набора мет в <head> из main, шапка/меню — из ветки дизайна,\n"
                  "  .foot__brand из main; потом build.py затирает маркеры в docs/.")
            return 2

        b = subprocess.run([sys.executable, "build.py", "--theme", a.theme, "--out", "docs"],
                           cwd=work, text=True, capture_output=True)
        if b.returncode:
            print(b.stdout + b.stderr)
            sys.exit("build.py упал — смотри ошибку выше.")
        print("\n" + b.stdout.strip())

        pages = sorted((work / "docs").rglob("*.html"))
        bad = placeholders_ok(pages)
        if bad:
            print("\nВ выводе остались плейсхолдеры/маркеры — лендить нельзя:")
            for line in bad[:20]:
                print("  " + line)
            return 3

        diffstat = git("diff", "--stat", "origin/main", cwd=work).stdout.strip()
        print("\nИзменения против main:\n" + (diffstat or "  (нет)"))
        new_pages = git("-c", "core.quotepath=false", "status", "--porcelain", cwd=work).stdout.strip()
        print("\nФайлов затронуто: %d" % len(new_pages.splitlines()))

        if not a.push:
            print("\nЭто был холостой прогон. Ничего не закоммичено. Для деплоя: --push")
            return 0

        git("add", "-A", cwd=work)
        name = git("config", "user.name", check=False).stdout.strip()
        email = git("config", "user.email", check=False).stdout.strip()
        ident = ["-c", "user.name=%s" % name, "-c", "user.email=%s" % email] if name and email else []
        msg = "merge: дизайн из %s" % branch
        git(*ident, "commit", "--no-verify", "-q", "-m", msg, "-m",
            "Источник: ветка %s (Onlook Studio). docs/ пересобран build.py." % branch, cwd=work)
        head = git("rev-parse", "HEAD", cwd=work).stdout.strip()
        git("push", "origin", "HEAD:main", cwd=work)
        print("\nЗапушено в main: %s (%s)" % (head[:9], msg))
        print("Проверь деплой: curl -s https://geekovski.ru/ | grep -c 'brand__logo'")
        return 0
    finally:
        git("worktree", "remove", "--force", str(work), check=False)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
