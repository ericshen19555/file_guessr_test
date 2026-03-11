"""
Diagnostic script: Check for stale/duplicate data caused by path inconsistency.
Run this to see if your SQLite and ES have leftover entries.
Usage: python diagnose_stale.py
"""
import sqlite3
import os
import re

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_guessr.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Check for path inconsistencies in SQLite
    rows = conn.execute("SELECT id, file_path FROM files").fetchall()
    print(f"=== SQLite: {len(rows)} total file records ===\n")

    mixed_slash = []
    missing_files = []
    duplicates = {}

    for row in rows:
        fp = row["file_path"]
        normalized = os.path.normpath(fp)

        # Check if stored path differs from normalized
        if fp != normalized:
            mixed_slash.append((row["id"], fp, normalized))

        # Check if the file still exists on disk
        if not os.path.exists(fp) and not os.path.exists(normalized):
            missing_files.append((row["id"], fp))

        # Track duplicates (same file, different path format)
        if normalized in duplicates:
            duplicates[normalized].append((row["id"], fp))
        else:
            duplicates[normalized] = [(row["id"], fp)]

    # Report mixed slashes
    if mixed_slash:
        print(f"⚠️  {len(mixed_slash)} paths with non-normalized separators:")
        for id_, fp, norm in mixed_slash[:10]:
            print(f"   ID {id_}: {fp}")
            print(f"        → should be: {norm}")
        if len(mixed_slash) > 10:
            print(f"   ... and {len(mixed_slash) - 10} more")
    else:
        print("✅ All paths are normalized")

    print()

    # Report duplicates
    real_dupes = {k: v for k, v in duplicates.items() if len(v) > 1}
    if real_dupes:
        print(f"⚠️  {len(real_dupes)} files with DUPLICATE entries (different path formats):")
        for norm, entries in list(real_dupes.items())[:5]:
            print(f"   File: {norm}")
            for id_, fp in entries:
                print(f"      ID {id_}: {fp}")
        if len(real_dupes) > 5:
            print(f"   ... and {len(real_dupes) - 5} more")
    else:
        print("✅ No duplicate entries")

    print()

    # Report missing files
    if missing_files:
        print(f"⚠️  {len(missing_files)} indexed files no longer exist on disk:")
        for id_, fp in missing_files[:10]:
            print(f"   ID {id_}: {fp}")
        if len(missing_files) > 10:
            print(f"   ... and {len(missing_files) - 10} more")
    else:
        print("✅ All indexed files exist on disk")

    print()

    # 2. Check watched folders
    folders = conn.execute("SELECT folder_path FROM watched_folders").fetchall()
    print(f"=== Watched folders: {len(folders)} ===")
    for f in folders:
        fp = f["folder_path"]
        norm = os.path.normpath(fp)
        status = "✅" if fp == norm else "⚠️  (not normalized)"
        exists = "exists" if os.path.isdir(norm) else "⚠️  MISSING"
        print(f"   {status} {fp} [{exists}]")

    conn.close()

    # 3. Offer to clean up
    if mixed_slash or real_dupes or missing_files:
        print("\n" + "=" * 50)
        print("建議：執行 Clear All 重新索引，或執行以下清理指令：")
        print("  python -c \"import database; database.clear_db(); print('Cleared!')\"")
    else:
        print("\n✅ 資料庫狀態正常，沒有發現殘留資料。")


if __name__ == "__main__":
    main()
