"""`python -m installer` -> the branded GUI installer.

Use `--cli` for a no-GUI install (same flow, terminal prompts) on headless boxes.
"""
import sys

if "--cli" in sys.argv:
    from installer import core
    dest = core.default_install_dir()
    core.bootstrap(dest, print)
    print(f"\nInstalled to {dest}. Run the first-time setup:")
    print(f'  "{core.venv_python(dest)}" -m namma_agent --setup')
else:
    from installer.gui import main
    main()
