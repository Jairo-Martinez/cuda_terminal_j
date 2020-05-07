import datetime
import os
import sys

import cudatext_keys as keys
import cudatext_cmd as cmds
import cudax_lib as ctx

from subprocess import Popen, PIPE, STDOUT
from threading import Thread, Lock
from time import sleep
from signal import SIGTERM

from cudatext import *
from enum import Enum

fn_icon = os.path.join(os.path.dirname(__file__), 'terminal.png')
config_file = 'cuda_terminal_j.json'

MAX_HISTORY = 20
IS_WIN = os.name == 'nt'
IS_MAC = sys.platform == 'darwin'
CODE_TABLE = ''
BASH_PROMPT = 'echo [`pwd`]$ '


def log(s):
    # Change conditional to True to log messages in a Debug process
    if False:
        plugin = os.path.basename(os.path.dirname(__file__))
        now = datetime.datetime.now()
        print(now.strftime("%H:%M:%S ") + plugin + ': ' + str(s))
    pass


class Config():
    mac_path = ':/usr/local/bin:/usr/local/sbin:/opt/local/bin:/opt/local/sbin'

    DEF_SHELL = r'%windir%\system32\cmd' if IS_WIN else 'bash'
    DEF_ADD_PROMPT = not IS_WIN
    DEF_CODE_TABLE = 'cp866' if IS_WIN else 'utf8'
    DEF_CUSTOM_PATH = mac_path if IS_MAC else ''

    class Opts(Enum):
        shell_path = 1
        custom_path = 2
        add_prompt = 3
        encoding = 4
        font_size = 5
        show_num = 6
        close_cmds = 7

    # Dictionary to save plugin configuration
    config = {}

    OPTS_META = [
        {'opt': Opts.shell_path.name,
         'cmt': 'Default shell path.',
         'def': DEF_SHELL,
         'frm': 'str',
         'chp': 'shell',
         },
        {'opt': Opts.custom_path.name,
         'cmt': 'This path will be added to PATH environment variable.',
         'def': DEF_CUSTOM_PATH,
         'frm': 'str',
         'chp': 'shell',
         },
        {'opt': Opts.add_prompt.name,
         'cmt': 'Control if Terminal need to show a prompt in no Windows systems.',
         'def': DEF_ADD_PROMPT,
         'frm': 'bool',
         'chp': 'shell',
         },
        {'opt': Opts.encoding.name,
         'cmt': 'Default character set.',
         'def': DEF_CODE_TABLE,
         'frm': 'str',
         'chp': 'output',
         },
        {'opt': Opts.font_size.name,
         'cmt': 'Terminal font size.',
         'def': 9,
         'frm': 'int',
         'chp': 'output',
         },
        {'opt': Opts.show_num.name,
         'cmt': 'Show line numbers in command window.',
         'def': False,
         'frm': 'bool',
         'chp': 'output',
         },
        {'opt': Opts.close_cmds.name,
         'cmt': ['Commands closing the Terminal and returns to Editor.',
                 'Space-separated values.'],
         'def': 'quit exit close',
         'frm': 'str',
         'chp': 'shell',
         },
    ]

    def __init__(self):
        pass

    def get_opt(self, path, val):
        return ctx.get_opt(path, val, user_json=config_file)

    def meta_default(self, key):
        return [it['def'] for it in self.OPTS_META if it['opt'] == key][0]

    def load_config(self):
        # Saving a dictionary with all plugin config
        for i in self.Opts:
            self.config[i.value] = self.get_opt(i.name,
                                                self.meta_default(i.name))

    def show_settings(self):
        import cuda_options_editor as op_ed

        subset = ''  # Key for isolated storage on plugin settings
        title = 'Terminal options'
        how = {'hide_lex_fil': True, 'stor_json': config_file}

        op_ed.OptEdD(
            path_keys_info=self.OPTS_META,
            subset=subset,
            how=how
        ).show(title)

        self.load_config()

    def get(self, key):
        return self.config[key.value]


class ControlTh(Thread):

    def __init__(self, Cmd):

        Thread.__init__(self)
        self.Cmd = Cmd

    def run(self):

        if not IS_WIN:
            while True:
                s = self.Cmd.p.stdout.read(1)
                if self.Cmd.p.poll() is not None:
                    s = "\nConsole process was terminated.\n\n".encode(CODE_TABLE)
                    with self.Cmd.block:
                        self.Cmd.btextchanged = True
                        self.Cmd.btext += s
                        self.Cmd.p = None
                        self.Cmd.stop_timer = True
                    break
                if s != '':
                    with self.Cmd.block:
                        self.Cmd.btextchanged = True
                        self.Cmd.btext += s
        else:
            while True:
                pp1 = self.Cmd.p.stdout.tell()
                self.Cmd.p.stdout.seek(0, 2)
                pp2 = self.Cmd.p.stdout.tell()
                self.Cmd.p.stdout.seek(pp1)
                if self.Cmd.p.poll() is not None:
                    s = "\nConsole process was terminated.\n\n".encode(CODE_TABLE)
                    with self.Cmd.block:
                        self.Cmd.btextchanged = True
                        self.Cmd.btext += s
                        self.Cmd.p = None
                        self.Cmd.stop_timer = True
                    break
                if pp2 != pp1:
                    s = self.Cmd.p.stdout.read(pp2-pp1)
                    with self.Cmd.block:
                        self.Cmd.btextchanged = True
                        self.Cmd.btext += s
                sleep(0.02)


class Command:

    def __init__(self):

        self.cfg = Config()
        self.cfg.load_config()

        # Create references to Config main methods
        self.opts = self.cfg.Opts
        self.get_cfg = self.cfg.get

        global CODE_TABLE
        CODE_TABLE = self.get_cfg(self.opts.encoding)

        self.shell_path = self.get_cfg(self.opts.shell_path)
        self.add_prompt = self.get_cfg(self.opts.add_prompt)
        self.custom_path = self.get_cfg(self.opts.custom_path)
        self.font_size = self.get_cfg(self.opts.font_size)
        self.show_num = self.get_cfg(self.opts.show_num)
        self.close_cmds = self.get_cfg(self.opts.close_cmds).split(' ')

        self.tick = 200
        self.stop_timer = False
        self.restart_p = False
        self.history = []
        self.h_menu = menu_proc(0, MENU_CREATE)

        self.title = 'Terminal'
        self.h_dlg = self.init_form()
        self.btextchanged = False

    def on_state(self, ed_self, state):

        if state == APPSTATE_THEME_UI:
            if self.h_dlg:
                self.memo.set_prop(PROP_RO, False)
                self.memo.action(EDACTION_UPDATE)
                self.memo.set_prop(PROP_RO, True)

    def on_start(self, ed_self):

        app_proc(PROC_BOTTOMPANEL_ADD_DIALOG, (self.title, self.h_dlg, fn_icon))
        self.p = None
        self.block = Lock()
        self.btext = b''

    def open(self):
        app_proc(PROC_BOTTOMPANEL_ACTIVATE, (self.title, True))

        if self.block.acquire(False):
            try:
                self.validate_p()
            finally:
                timer_proc(TIMER_START, self.timer_update, self.tick, tag='')


    def init_form(self):

        h = dlg_proc(0, DLG_CREATE)
        dlg_proc(h, DLG_PROP_SET, prop={
            'border': False,
            'keypreview': True,
            'on_key_down': self.form_key_down,
            'on_show': self.form_show,
            'on_hide': self.form_hide,
            })

        n = dlg_proc(h, DLG_CTL_ADD, 'colorpanel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'pnl_editor',
            'border': False,
            'align': ALIGN_CLIENT,
            })

        n = dlg_proc(h, DLG_CTL_ADD, 'editor')
        self.memo = Editor(dlg_proc(h, DLG_CTL_HANDLE, index=n))
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'memo',
            'p': 'pnl_editor',
            'align': ALIGN_CLIENT,
            'font_size': self.font_size,
            })

        n = dlg_proc(h, DLG_CTL_ADD, 'colorpanel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'pnl_bottom',
            'border': False,
            'align': ALIGN_BOTTOM,
            'h': 28,
            })

        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'break',
            'p': 'pnl_bottom',
            'w': 60,
            'align': ALIGN_RIGHT,
            'cap': 'Break',
            'hint': 'Hotkey: Break',
            'on_change': self.button_break_click,
            })

        n = dlg_proc(h, DLG_CTL_ADD, 'colorpanel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'pnl_input',
            'p': 'pnl_bottom',
            'border': True,
            'a_l': ('', '['),
            'a_t': ('', '['),
            'a_r': ('break', '['),
            'a_b': ('', ']'),
            'props': (0, self.get_editor_bg('EdTextBg')),
            })

        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'down',
            'p': 'pnl_input',
            'w': 22,
            'border': False,
            'align': ALIGN_LEFT,
            'cap': 'Hist',
            'hint': 'Show history commands',
            'on_change': self.show_history
            })

        self.n_btn_down = dlg_proc(h, DLG_CTL_HANDLE, index=n)

        button_proc(self.n_btn_down, BTN_SET_KIND, BTNKIND_ICON_ONLY)
        button_proc(self.n_btn_down, BTN_SET_ARROW, True)
        button_proc(self.n_btn_down, BTN_SET_ARROW_ALIGN, 'C')

        n = dlg_proc(h, DLG_CTL_ADD, 'edit')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
            'name': 'input',
            'border': False,
            'p': 'pnl_input',
            'a_l': ('down', ']'),
            'a_t': ('', '['),
            'a_r': ('', ']'),
            'a_b': ('', ']'),
            'sp_t': 3,
            'sp_l': 3,
            'font_name': ctx.get_opt('font_name'),
            'font_size': self.font_size,
            'color': self.get_editor_bg('EdTextBg'),
            'act': True,
            # 'on_change': self.edit_search_change,
            })

        self.n_cmd_input = n

        self.memo.set_prop(PROP_RO, True)
        self.memo.set_prop(PROP_CARET_VIRTUAL, False)
        self.memo.set_prop(PROP_UNPRINTED_SHOW, False)
        self.memo.set_prop(PROP_MARGIN, 2000)
        self.memo.set_prop(PROP_LAST_LINE_ON_TOP, False)
        self.memo.set_prop(PROP_HILITE_CUR_LINE, False)
        self.memo.set_prop(PROP_HILITE_CUR_COL, False)
        self.memo.set_prop(PROP_MODERN_SCROLLBAR, True)
        self.memo.set_prop(PROP_MINIMAP, False)
        self.memo.set_prop(PROP_MICROMAP, False)

        if self.show_num:
            self.memo.set_prop(PROP_GUTTER_NUM, True)
            self.memo.set_prop(PROP_GUTTER_STATES, False)
            self.memo.set_prop(PROP_GUTTER_FOLD, False)
            self.memo.set_prop(PROP_GUTTER_BM, False)
        else:
            self.memo.set_prop(PROP_GUTTER_ALL, False)

        dlg_proc(h , DLG_CTL_FOCUS, name='input')

        return h

    def validate_p(self):
        if not self.p:
            env = os.environ
            if self.custom_path:
                env['PATH'] += self.custom_path

            self.p = Popen(
                os.path.expandvars(self.shell_path),
                stdin=PIPE,
                stdout=PIPE,
                stderr=STDOUT,
                shell=IS_WIN,
                bufsize=0,
                env=env
                )

            # w, self.r = os.pipe()
            self.p.stdin.flush()
            self.CtlTh = ControlTh(self)
            self.CtlTh.start()

    def config(self):

        self.cfg.show_settings()

    def timer_update(self, tag='', info=''):
        # log("Entering in timer_update")
        self.btextchanged = False
        self.block.release()

        if self.stop_timer:
            timer_proc(TIMER_STOP, self.timer_update, 0)
            if self.restart_p:
                self.restart_p = False
                self.form_show(0, 0)
            return

        sleep(0.03)
        self.block.acquire()
        if self.btextchanged:
            self.update_output()

    def get_text(self, index):
        return dlg_proc(self.h_dlg, DLG_CTL_PROP_GET, index=index)['val']

    def set_text(self, index, val):
        dlg_proc(self.h_dlg, DLG_CTL_PROP_SET, index=index, prop={'val': val})

    def form_key_down(self, id_dlg, id_ctl, data='', info=''):

        # Enter
        if id_ctl == keys.VK_ENTER:
            text = self.get_text(self.n_cmd_input)
            self.set_text(self.n_cmd_input, '')
            self.run_cmd(text)
            return False

        # history menu
        if (id_ctl in [keys.VK_DOWN, keys.VK_UP]):
            self.show_history(self.h_dlg, self.n_btn_down)
            return False

        # Escape: go to editor
        if (id_ctl == keys.VK_ESCAPE) and (data == ''):
            self.close_dlg()
            return False

        # Break (cannot react to Ctrl+Break)
        if (id_ctl == keys.VK_PAUSE):
            self.button_break_click(0, 0, restart=False)
            return False

    def close_dlg(self):
        # Stops the timer
        self.stop_timer = True
        ed.focus()
        ed.cmd(cmds.cmd_ToggleBottomPanel)


    def form_hide(self, id_dlg, id_ctl, data='', info=''):
        self.stop_timer = True

    def form_show(self, id_dlg, id_ctl, data='', info=''):
        self.stop_timer = False
        if self.block.acquire(False):
            try:
                self.validate_p()

            finally:
                timer_proc(TIMER_START, self.timer_update, self.tick, tag='')

        dlg_proc(self.h_dlg, DLG_CTL_FOCUS, name='input')

    def show_history(self, id_dlg, id_ctl, data='', info=''):

        menu_proc(self.h_menu, MENU_CLEAR)
        for (index, item) in enumerate(self.history):
            menu_proc(self.h_menu, MENU_ADD,
                      index=0,
                      caption=item,
                      command='module=cuda_terminal_j;cmd=run_cmd;info=%s;' % item,
                      )

        prop = dlg_proc(self.h_dlg, DLG_CTL_PROP_GET, name='pnl_bottom')
        x, y = prop['x'], prop['y']
        x, y = dlg_proc(self.h_dlg, DLG_COORD_LOCAL_TO_SCREEN, index=x, index2=y)
        menu_proc(self.h_menu, MENU_SHOW, command=(x, y))

    def run_cmd(self, text):

        # Del lead spaces
        text = text.strip()

        if not text:
            return

        while len(self.history) > MAX_HISTORY:
            del self.history[0]

        try:
            n = self.history.index(text)
            del self.history[n]
        except Exception as e:
            pass

        self.history += [text]
        self.set_text(self.n_cmd_input, '')

        # Validate if command is a closing word
        if text in self.close_cmds:
            self.close_dlg()
            return

        # Support password input in sudo
        if not IS_WIN and text.startswith('sudo '):
            text = 'sudo --stdin '+text[5:]

        # Don't write prompt, if sudo asks for password
        line = self.memo.get_text_line(self.memo.get_line_count()-1)
        is_sudo = not IS_WIN and line.startswith('[sudo] ')

        if self.add_prompt and not IS_WIN and not is_sudo:
            self.p.stdin.write((BASH_PROMPT+text+'\n').encode(CODE_TABLE))
            self.p.stdin.flush()

        if self.p:
            self.p.stdin.write((text+'\n').encode(CODE_TABLE))
            self.p.stdin.flush()

    def add_output(self, s):
        self.memo.set_prop(PROP_RO, False)
        text = self.memo.get_text_all()
        self.memo.set_text_all(text+s)
        self.memo.set_prop(PROP_RO, True)

        self.memo.cmd(cmds.cCommand_GotoTextEnd)

    def update_output(self):
        s = self.btext.decode(CODE_TABLE)
        self.memo.set_prop(PROP_RO, False)
        self.memo.set_text_all(s)
        self.memo.set_prop(PROP_RO, True)

        self.memo.cmd(cmds.cCommand_GotoTextEnd)

    def on_exit(self, ed_self):

        timer_proc(TIMER_STOP, self.timer_update, 0)
        if not self.p:
            return

        try:
            self.p.send_signal(SIGTERM)
        except Exception as e:
            pass

        if IS_WIN:
            self.p.wait()
        while self.p:
            self.timer_update()

        self.block.release()
        sleep(0.25)

    def button_break_click(self, id_dlg, id_ctl, data='', info='', restart=True):
        dlg_proc(self.h_dlg, DLG_CTL_FOCUS, name='input')

        if restart:
            self.restart_p = True

        if IS_WIN:
            try:
                self.p.send_signal(SIGTERM)
            except Exception as e:
                pass
            self.p.wait()
        else:
            try:
                self.p.send_signal(SIGTERM)
            except Exception as e:
                pass

    def get_editor_bg(self, item):
        theme = app_proc(PROC_THEME_UI_DICT_GET, '')
        color = theme[item]['color']

        return hex(int(color))