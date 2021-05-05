import os
from contextlib import contextmanager
from collections import namedtuple

from cudatext import *
from cudax_lib import get_translation, get_app_default_opts, OPT2PROP
FILE_OPTS = OPT2PROP # to check if option can be in file scope

import traceback

# dbg
import time

"""
#DONE
* search
* OK,Cancel,Apply
* sorts
* scope change - update current value
* value editing for different values
* update list on opt change
* fix val display: int2s, str2s
* list columns choice
* ctrl+f for filter + hide/show
* column widths
* remember UI
* filter history
* user keys for numbers are sorted before others
* fisx sorting
* format other scope values
* edit and combo - fonts size
* focus to filter on filter
* <Escape> in filter to unfilter and hide filter
* better way to get option value+scoped

#TODO:
* list changes in dlg-statusbar + hover popup
* add help
* some options not applied (font)

* different color fo unapplied propery value in editor?

* editor line state coloring for modified/unapplied("saved") options?
* show user/lexer/file option-values for selected option?
* indicate qued option change in list?
* os scale
* different filter background?


file:///mnt/H/cuda/__FM/data/themes/cobalt.cuda-theme-ui
"""

_   = get_translation(__file__)  # I18N


OptChange = namedtuple('OptChange', 'name scope value lexer old_value')

fn_icons = {
    'asc': 'asc.png', # ascending order
    'desc': 'desc.png', # descending
}
PLING_HISTORY_JSON  = os.path.join(app_path(APP_DIR_SETTINGS), 'plugin history.json')
FORMS_CFG_JSON = os.path.join(app_path(APP_DIR_SETTINGS), 'forms data.json')
PLING_KEY = 'dlg_preferences'
STATE_KEY_TREE_W = 'tree_w'
STATE_KEY_DESCR_MEMO_H = 'descr_memo_h'
STATE_KEY_FILTER_STR = 'filter_str'
STATE_KEY_FILTER_HIST = 'filter_history'
STATE_KEY_FILTER_VISIBLE = 'filter_visible'
STATE_KEY_COL_CFG = 'columns'
STATE_KEY_SORT_COL = 'sort_column'
STATE_KEY_SEL_OPT = 'selected_option'


IS_DBG = False
LOG = False


VK_ENTER = 13
VK_F = ord('F')
VK_ESCAPE = 27
LIST_SEP = chr(1)

BTN_H = 24
PAD = 2

# colores
COL_FONT = 0
COL_SPLITTER = 0

TREE_ITEM_ALL = '[ All ]'

# columns
COL_SECTION     = 'Section'
COL_OPT_NAME    = 'Option'
COL_MODIFIED    = '!'
COL_VAL_DEFAULT = 'Default'
COL_VAL_USER    = 'User'
COL_VAL_LEX     = 'Lexer'
COL_VAL_FILE    = 'File'
COL_VAL_MAIN    = 'Value' # current value -- most specific f,l,u,def value

OPTS_COLUMN_MAP = {
    COL_SECTION     : 'chp',
    COL_OPT_NAME    : 'opt',
    COL_MODIFIED    : '!',
    COL_VAL_DEFAULT : 'def',
    COL_VAL_USER    : 'uval',
    COL_VAL_LEX     : 'lval',
    COL_VAL_FILE    : 'fval',
    # + Value - most specific scope value
}

# order in UI
COLS_LIST = [
    COL_SECTION,
    COL_OPT_NAME,
    COL_MODIFIED,
    COL_VAL_DEFAULT,
    COL_VAL_MAIN,
    COL_VAL_USER,
    COL_VAL_LEX,
    COL_VAL_FILE,
]

opt_col_cfg = [("Option", 70), ("Value", 100)]

ui_max_history_edits = 20
font_name = None
font_size = None

filter_history = []


def get_tree_path_names(h_tree, item_id, l=None):
    ''' returns list, node names starting with deepest
    '''
    if l is None:
        l = []
    prop = tree_proc(h_tree, TREE_ITEM_GET_PROPS, id_item=item_id)
    l.append(prop['text'])

    parent_id = prop.get('parent')
    if parent_id:
        get_tree_path_names(h_tree, parent_id, l)
    return l

def get_tree_path(h_tree, item_id):
    """ tree path for tree item
    """
    path_names = get_tree_path_names(h_tree, item_id)
    path_names.reverse()
    return '/'.join(path_names)

@contextmanager
def ignore_edit(h, ed_):
    """ turns off PROP_RO + deactivates Editor -- then restores
        ? to not send `on_change` when changing `editor_combo` text
    """
    is_ro = ed_.get_prop(PROP_RO)
    if is_ro:
        ed_.set_prop(PROP_RO, False)

    h_ed = ed_.get_prop(PROP_HANDLE_SELF)
    #NOTE: widgets are never deleted here, so `DLG_CTL_COUNT` should not be a problem
    for n in range(dlg_proc(h, DLG_CTL_COUNT)):
        h_ctl = dlg_proc(h, DLG_CTL_HANDLE, index=n)
        if h_ed == h_ctl:
            # disable temporarily
            dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={'act': False})
            break

    try:
        yield
    finally:
        if is_ro:
            ed_.set_prop(PROP_RO, True)
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={'act': True})


def map_option_value(opt, val=None, caption=None):
    """ for map options - returns caption for provided 'val'ue, or value for provided 'caption'
    """
    frm = opt['frm']
    if frm in ['int2s', 'str2s']:
        jdc = opt['jdc'] # list('(a) by Alt+click', ...)
        dct = opt['dct'] # list(['a', 'by Alt+click'], ...)

        if val is not None:
            for i,item in enumerate(dct):
                if item[0] == val:
                    return jdc[i]     # return str

        elif caption is not None:
            ind = jdc.index(caption)
            val, _cap = dct[ind]
            return val

        else:
            raise Exception(f'OptionMapValueError: require "val" or "caption"')
    else:
        raise Exception(f'OptionMapValueError: Unsupported option format: {opt["opt"], opt["frm"]}')
    raise Exception(f'OptionMapValueError: Couldn"t find: {val, caption, opt}')


def json_update(path, key, val):
    """ loads json at 'path' if exists, puts 'k':'v' into it and saves
    """
    import json

    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            j = json.load(f)
    else:
        j = {}

    j[key] = val
    j_str = json.dumps(j, indent=2)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(j_str)

def format_opt_change(ch):
    scope_str = ch.scope
    if   ch.scope == 'u': scope_str = 'User'
    elif ch.scope == 'l': scope_str = 'Lexer: {ch.lexer}'
    elif ch.scope == 'f': scope_str = 'File: ' +os.path.basename(ed.get_filename())

    if ch.value is None:    val_str = 'reset'
    else:                   val_str = f'{ch.old_value} -> {ch.value}'

    return f'{ch.name} [{scope_str}] {val_str}'


class DialogMK2:

    def __init__(self, optman):
        """ optman -- cd_opts_dlg.py/OptionsMan
        """
        global ui_max_history_edits
        global font_name
        global font_size

        ui_max_history_edits = optman.get_scope_value('ui_max_history_edits', scope='u',
                                                        default=ui_max_history_edits)
        _font_name_opt = optman.get_opt('font_name')
        _font_size_opt = optman.get_opt('font_size')
        font_name = optman.get_opt_active_value(_font_name_opt, is_ui=False)
        font_size = optman.get_opt_active_value(_font_size_opt, is_ui=False)

        self._form_rect = {} # dict - x,y,w,h
        self._state = {}

        self.optman = optman
        self._load_dlg_cfg()

        self.current_sort = self._state.get(STATE_KEY_SORT_COL, 'Option')
        self.sort_reverse = False
        self._last_applied_filter = None
        self._cur_opt_name = None

        self.h = None
        self._h_tree = None
        self._h_col_menu = None
        self._h_help = None
        self._cur_value_ed = 'str' # type for: _set_value_editor()

        self.val_eds = ValueEds(self.on_opt_val_edit)

        self._opt_changes = []
        self._head_spls = [] # inds
        self._lb_icon_inds = {} # listbox icons
        self._list_opt_names = [] # current displayed list of option-names
        # '' -> User -- showing default value, edited value will be added to 'user' scope
        self._scope_captions = {'u': 'User', '': 'User', 'def': 'User'} # 'u' -> 'User' ... expanded alter
        self._col_toggle_cmds = {} # column name -> toggle lambda -- for menu, to toggle list columns


    @property
    def filter_val(self):
        if self.h:
            return self._filter_ed.get_text_all()
        return ''
    @filter_val.setter
    def filter_val(self, value): #SKIP
        if self.h:
            self._filter_ed.set_text_all(str(value))

    @property
    def columns(self):
        """ returns (column_captions, column_widths)
        """
        captions = []
        widths = []
        _total_w = sum(w for name,w in opt_col_cfg if name != '!') # total width withoud '!'<-px
        for caption,w in opt_col_cfg:
            captions.append(caption)

            # width: to negative percentages for listbox -- except '!' <- in px
            if caption != '!':
                w = -round(w/_total_w*100)
            widths.append(w)

        return captions,widths

    @property
    def scope(self):
        """ returns current scope char: u,l,f
        """
        scope_str = self.scope_ed.get_text_all()
        if scope_str == 'User':             return 'u'
        elif scope_str.startswith('Lexer'): return 'l'  # for future - show lexer name in scope
        elif scope_str.startswith('File'):  return 'f'  #


    def _load_dlg_cfg(self):
        import json

        if os.path.exists(FORMS_CFG_JSON):
            with open(FORMS_CFG_JSON, 'r', encoding='utf-8') as f:
                j_form = json.load(f).get(PLING_KEY)
            if j_form:
                self._form_rect = {k:v for k,v in j_form.items()
                                        if v  and  k in {'x', 'y', 'w', 'h'}}

        if os.path.exists(PLING_HISTORY_JSON):
            with open(PLING_HISTORY_JSON, 'r', encoding='utf-8') as f:
                j = json.load(f).get(PLING_KEY)
            if j:
                _state_keys = {
                    STATE_KEY_TREE_W,
                    STATE_KEY_DESCR_MEMO_H,
                    STATE_KEY_FILTER_STR,
                    STATE_KEY_FILTER_VISIBLE,
                    STATE_KEY_SEL_OPT,
                    STATE_KEY_SORT_COL,
                }
                self._state = {k:v for k,v in j.items()  if k in _state_keys}

                _filt_hist = j.get(STATE_KEY_FILTER_HIST)
                if _filt_hist:
                    filter_history.clear()
                    filter_history.extend(_filt_hist)

                _col_cfg = j.get(STATE_KEY_COL_CFG)
                if _col_cfg:
                    opt_col_cfg.clear()
                    opt_col_cfg.extend(_col_cfg)
                pass;       LOG and print(f' --- Loaded state: {json.dumps(j, indent=4)}')


    def _save_dlg_cfg(self):
        # window position/dimensions
        form_prop = dlg_proc(self.h, DLG_PROP_GET)
        j_form = {'x':form_prop['x'], 'y':form_prop['y'], 'w':form_prop['w'], 'h':form_prop['h']}
        json_update(FORMS_CFG_JSON, key=PLING_KEY, val=j_form)

        # states
        j = {}
        j[STATE_KEY_TREE_W] = dlg_proc(self.h, DLG_CTL_PROP_GET, name='category_tree')['w']
        j[STATE_KEY_DESCR_MEMO_H] = dlg_proc(self.h, DLG_CTL_PROP_GET, name='descr_memo')['h']
        j[STATE_KEY_FILTER_STR] = self.filter_val
        j[STATE_KEY_FILTER_HIST] = filter_history
        j[STATE_KEY_FILTER_VISIBLE] = dlg_proc(self.h, DLG_CTL_PROP_GET, name='panel_filter')['vis']
        j[STATE_KEY_SORT_COL] = self.current_sort
        j[STATE_KEY_SEL_OPT] = self._cur_opt_name

        j[STATE_KEY_COL_CFG] = opt_col_cfg

        json_update(PLING_HISTORY_JSON,  PLING_KEY,  j )


    def show(self):
        if not self.h:
            self.h, self.edt = self.init_form()

        self._fill_tree(self.optman.tree['kids'])

        self.update_list_layout()

        # restore filter
        _filter_val = self._state.get(STATE_KEY_FILTER_STR, '')
        self.set_filter(_filter_val)
        if _filter_val:
            self.toggle_filter(show=True)

        # restore selected-option (+show it)
        last_sel_opt = self._state.get(STATE_KEY_SEL_OPT)
        if last_sel_opt  and  last_sel_opt in self._list_opt_names:
            _ind = self._list_opt_names.index(last_sel_opt)
            listbox_proc(self._h_list, LISTBOX_SET_SEL, index=_ind)
            _top = max(0, _ind-3)
            listbox_proc(self._h_list, LISTBOX_SET_TOP, index=_top)
            #### click event
            self._on_opt_click(id_dlg=self.h, id_ctl=-1)

        # DBG #############
        if IS_DBG:
            DialogMK2._dlg = self
            cmds = [    'from cuda_options_editor_my.dlg import DialogMK2',
                        'globals()["dlg"] = DialogMK2._dlg',]
            app_proc(PROC_EXEC_PYTHON, '\n'.join(cmds))
            del DialogMK2._dlg
        ###########

        dlg_proc(self.h, DLG_SHOW_NONMODAL)

    def init_form(self):
        global COL_FONT
        global COL_SPLITTER

        h = dlg_proc(0, DLG_CREATE)

        colors = app_proc(PROC_THEME_UI_DICT_GET, '')
        COL_FONT = colors['EdTextFont']['color']
        COL_SPLITTER = colors['SplitMain']['color']
        #COL_SPLITTER = colors['ScrollFill']['color']
        #COL_SPLITTER = colors['EdBorderFocused']['color']
        #COL_SPLITTER = colors['EdTextFont']['color']
        #COL_SPLITTER = colors['ButtonBorderOver']['color']
        #color_form_bg = colors['TabPassive']['color']
        #color_form_bg = colors['EdTextBg']['color']
        color_form_bg = colors['ButtonBorderPassive']['color']

        ###### FORM #######################
        dlg_proc(h, DLG_PROP_SET, prop={
                'cap': 'CudaText Preferences',
                'w': 600, 'h': 400,
                'border': DBORDER_SIZE,
                'color': color_form_bg,
                #'on_mouse_exit': self.dlgcolor_mouse_exit,
                'keypreview': True,
                'on_key_down': self._on_key,
                'on_close': lambda *args, **vargs: self._save_dlg_cfg(),

                **self._form_rect, # restore saved - x,y,w,h
                })

        ###### MAIN PANEL
        n = dlg_proc(h, DLG_CTL_ADD, 'panel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n,   prop={
                'name': 'panel_main',
                'align': ALIGN_CLIENT,
                'sp_l': PAD*2, 'sp_t': PAD*2, 'sp_r': PAD*2, 'sp_b': PAD*2 + BTN_H + PAD*2,
                })


        ### tree ##########################
        n = dlg_proc(h, DLG_CTL_ADD, 'treeview')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'category_tree',
                'p': 'panel_main',
                'align': ALIGN_LEFT,
                'w': self._state.get(STATE_KEY_TREE_W, 100),
                #'sp_r': PAD,
                'on_change': self._on_tree_click,
                })
        self._h_tree = dlg_proc(h, DLG_CTL_HANDLE, index=n)
        tree_proc(self._h_tree, TREE_THEME)


        ### RIGHT PANEL #########################
        n = dlg_proc(h, DLG_CTL_ADD, 'panel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n,   prop={
                'name': 'panel_right',
                'p': 'panel_main',
                'align': ALIGN_CLIENT,
                #'sp_l': PAD,
                })
        # listbox ##########
        n = dlg_proc(h, DLG_CTL_ADD, 'listbox_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'p': 'panel_right',
                'align': ALIGN_CLIENT,
                #'sp_b': PAD,
                'on_click': self._on_opt_click,
                'on_click_header': self._on_header_click,
                'on_menu': self.listbox_menu,
                })
        self._h_list = dlg_proc(h, DLG_CTL_HANDLE, index=n)

        ### FILTER panel ############################
        n = dlg_proc(h, DLG_CTL_ADD, 'panel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'panel_filter',
                'p': 'panel_right',
                'align': ALIGN_BOTTOM,  'h': BTN_H, 'max_h': BTN_H,
                'vis': self._state.get(STATE_KEY_FILTER_VISIBLE, False),
                })
        # filter combo ##########
        n = dlg_proc(h, DLG_CTL_ADD, 'editor_combo')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'filter',
                'p': 'panel_filter',
                'h': BTN_H, 'max_h': BTN_H,
                'align': ALIGN_CLIENT,
                'sp_t': PAD, 'sp_r': 20, 'sp_b': PAD,
                #'a_l': None,   'a_r': ('', ']'),  'a_t': ('', '['),
                'on_change': self._on_filter,
                'on_key_down': self._on_filter, # for later -- live filter
                })
        h_ed = dlg_proc(h, DLG_CTL_HANDLE, index=n)
        self._filter_ed = Editor(h_ed)
        # filter label
        n = dlg_proc(h, DLG_CTL_ADD, 'label')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'p': 'panel_filter',
                'sp_l': 8, 'sp_t': 6,
                'align': ALIGN_LEFT,
                'cap': 'Filter: ',
                'font_color': COL_FONT,
                })


        ### BOTTOM PANEL ###############################
        n = dlg_proc(h, DLG_CTL_ADD, 'panel')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n,   prop={
                'name': 'panel_value',
                'p': 'panel_right',
                'align': ALIGN_BOTTOM,
                'h': 120,
                'sp_t': PAD,
                })
        # scope combo ##########
        n = dlg_proc(h, DLG_CTL_ADD, 'editor_combo')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'scope',
                'p': 'panel_value',
                'h': BTN_H, 'max_h': BTN_H,       'w': 100, 'max_w': 100,
                'a_l': None,   'a_r': ('', ']'),  'a_t': ('', '['),
                'act': True,
                'on_change': self._on_scope_change,
                })
        h_scope_ed = dlg_proc(h, DLG_CTL_HANDLE, index=n)
        # scope label ###
        n = dlg_proc(h, DLG_CTL_ADD, 'label')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'scope_label',
                'p': 'panel_value',
                'h': BTN_H, 'max_h': BTN_H,
                'a_l': None,   'a_r': ('scope', '['),  'a_t': ('scope', '-'),
                'sp_t': 3,
                'cap': 'Scope: ',
                'font_color': COL_FONT,
                })
        # btn reset ###########
        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': ValueEds.VALUE_ED_RESET,
                'p': 'panel_value',
                'h': BTN_H, 'max_h': BTN_H,
                'w': 60, 'max_w': 60,
                'a_l': None,   'a_r': ('scope_label', '['),  'a_t': ('', '['),
                'sp_l': PAD, 'sp_r': 32,
                'cap':'Reset',
                'on_change': self._on_reset,
                })
        # option description #########
        n = dlg_proc(h, DLG_CTL_ADD, 'editor')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'descr_memo',
                'p': 'panel_value',
                'sp_t': BTN_H + PAD,
                'align': ALIGN_CLIENT,
                'h': self._state.get(STATE_KEY_DESCR_MEMO_H, 100),
                })
        h_ed = dlg_proc(h, DLG_CTL_HANDLE, index=n)
        edt = Editor(h_ed)


        ### SPLITTERS ###
        # list--opt_description
        n = dlg_proc(h, DLG_CTL_ADD, 'splitter')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'p': 'panel_right',
                'align': ALIGN_BOTTOM,
                'x': 0, 'y': 50, 'h': 4,
                'color': COL_SPLITTER,
                })
        # tree--list
        n = dlg_proc(h, DLG_CTL_ADD, 'splitter')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'p': 'panel_main',
                'align': ALIGN_LEFT,
                'x': 100, 'y': 0, 'w': 4,
                'color': COL_SPLITTER,
                })


        ### Bottom Btns ###################
        # OK #######
        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'btn_ok',
                'h': BTN_H, 'max_h': BTN_H,
                'w': 60, 'max_w': 60,
                'a_l': None, 'a_t': None, 'a_r': ('', ']'),  'a_b': ('', ']'),
                'sp_r': PAD*2, 'sp_b': PAD*2,
                'cap':'OK',
                'on_change': lambda *args, **vargs: (self.apply_changes(closing=True), self.close()),
                })
        # Apply #######
        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'name': 'btn_apply',
                'h': BTN_H, 'max_h': BTN_H,
                'w': 60, 'max_w': 60,
                'a_l': None, 'a_t': None, 'a_r': ('btn_ok', '['),  'a_b': ('', ']'),
                'sp_r': PAD*2, 'sp_b': PAD*2,
                'cap':'Apply',
                'on_change': lambda *args, **vargs: self.apply_changes(),
                })
        # Cancel #######
        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'h': BTN_H, 'max_h': BTN_H,
                'w': 60, 'max_w': 60,
                'a_l': None, 'a_t': None, 'a_r': ('btn_apply', '['),  'a_b': ('', ']'),
                'sp_r': PAD*2, 'sp_b': PAD*2,
                'cap':'Close',
                'on_change': lambda *args, **vargs: self.close(),
                })
        # help #######
        n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
        dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                'h': BTN_H, 'max_h': BTN_H,
                'w': 60, 'max_w': 60,
                'a_l': ('', '['),  'a_t': None, 'a_r': None, 'a_b': ('', ']'),
                'sp_l': PAD*2, 'sp_b': PAD*2,
                'cap':'Help',
                'on_change': self.dlg_help,
                })

        ### listbox
        listbox_proc(self._h_list, LISTBOX_SET_COLUMN_SEP, text=LIST_SEP)
        # + icons
        h_iml = imagelist_proc(0, IMAGELIST_CREATE)
        _icons_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icons')
        for name,fn_icon in fn_icons.items():
            _path = os.path.join(_icons_dir, fn_icon)
            imind = imagelist_proc(h_iml, IMAGELIST_ADD, _path)
            self._lb_icon_inds[name] = imind
        listbox_proc(self._h_list, LISTBOX_SET_HEADER_IMAGELIST, text=h_iml)


        edt.set_prop(PROP_GUTTER_ALL, False)
        edt.set_prop(PROP_MINIMAP, False)
        edt.set_prop(PROP_MICROMAP, False)
        edt.set_prop(PROP_LAST_LINE_ON_TOP, False)
        edt.set_prop(PROP_WRAP, WRAP_ON_WINDOW)

        scopes = ['User']
        lex = ed.get_prop(PROP_LEXER_FILE)
        if lex:
            scopes.append('Lexer: '+lex)
            self._scope_captions['l'] = scopes[-1]
        if ed.get_filename():
            filename = os.path.split(ed.get_filename())[1]
            scopes.append('File: '+filename)
            self._scope_captions['f'] = scopes[-1]
        self.scope_ed = Editor(h_scope_ed)
        #self.scope_ed.set_prop(PROP_FONT, ('Arial', '8'))
        self.scope_ed.set_prop(PROP_RO, True)
        self.scope_ed.set_prop(PROP_COMBO_ITEMS, '\n'.join(scopes))

        font = (font_name, font_size) if font_name and font_size else None
        if font:
            edt.set_prop(PROP_FONT, font)
            self.scope_ed.set_prop(PROP_FONT, font)
            self._filter_ed.set_prop(PROP_FONT, font)

        dlg_proc(h, DLG_SCALE)
        return h, edt

    def update_list(self, opts):
        column_names, _col_widths = self.columns
        columns_items = []
        _value_cols = {COL_VAL_DEFAULT,  COL_VAL_USER,  COL_VAL_LEX,  COL_VAL_FILE}
        for col_title in column_names:
            if col_title == COL_VAL_MAIN:
                col_values = [str(self.optman.get_opt_active_value(op, is_ui=True)) for op in opts]

            elif col_title in _value_cols:
                _col_key = OPTS_COLUMN_MAP.get(col_title)
                _scope = 'def'  if _col_key == 'def' else  _col_key[0] # 'uval' -> 'u',  'def' -> 'def'
                col_values = [str(self.optman.get_opt_scope_value(op, _scope, is_ui=True)) for op in opts]

            else:
                _col_key = OPTS_COLUMN_MAP.get(col_title)
                col_values = [str(op.get(_col_key, '')) for op in opts] # can't use generator - _col_key

            columns_items.append(col_values)

        self._list_opt_names = [op['opt'] for op in opts]

        listbox_proc(self._h_list, LISTBOX_DELETE_ALL)

        _addedn = 0
        _max_seps = 0
        for row in zip(*columns_items):
            row_txt = LIST_SEP.join(row)
            _max_seps = row_txt.count(LIST_SEP)

            listbox_proc(self._h_list, LISTBOX_ADD, index=-1, text=row_txt)
            _addedn += 1
        _rows = listbox_proc(self._h_list, LISTBOX_GET_COUNT)

        # select  current option
        if self._list_opt_names:
            ind = 0
            if self._cur_opt_name  and  self._cur_opt_name in self._list_opt_names:
                ind = self._list_opt_names.index(self._cur_opt_name)
            #listbox_proc(self._h_list, LISTBOX_SET_TOP, max(0, ind-3)) # selecting is not helpful
            listbox_proc(self._h_list, LISTBOX_SET_SEL, ind)

    def update_list_layout(self):
        # columns
        column_captions, column_widths = self.columns
        column_widths[-1] = 0   # last col to 'fill' - to avoid h-scrollbar
        column_captions_str = LIST_SEP.join(column_captions)
        listbox_proc(self._h_list, LISTBOX_SET_COLUMNS, text=column_widths) # width<0 means value in %
        listbox_proc(self._h_list, LISTBOX_SET_HEADER, text=column_captions_str)

        # sort icons
        if self.current_sort:
            sort_col_ind = column_captions.index(self.current_sort)
            _order_name = 'asc'  if not self.sort_reverse else  'desc'
            _icon_ind = self._lb_icon_inds[_order_name]
            header_icon_cfg = [-1]*sort_col_ind + [_icon_ind] # ~[-1, -1, -1, ind]
            listbox_proc(self._h_list, LISTBOX_SET_HEADER_IMAGEINDEXES, text=header_icon_cfg)

    def get_filtered_opts(self):
        sort_field = OPTS_COLUMN_MAP.get(self.current_sort, self.current_sort)
        return self.optman.get_list(self.filter_val, sort_field, reverse=self.sort_reverse)

    def set_filter(self, filter_str, tree_click=False):
        if self._last_applied_filter == filter_str:
            return

        if tree_click and not filter_str:
            self.toggle_filter(show=False)

        self._last_applied_filter = filter_str
        self.filter_val = filter_str

        opts = self.get_filtered_opts()
        pass;       LOG and print(f' __ set_filter: opts len: {len(opts)}')
        self.update_list(opts)

        # history
        if filter_str:
            try:
                ind = filter_history.index(filter_str)
                del filter_history[ind]
            except ValueError:
                pass

            filter_history.append(filter_str)
            del filter_history[:-ui_max_history_edits]

        # update combo items
        self._filter_ed.set_prop(PROP_COMBO_ITEMS, '\n'.join(reversed(filter_history)))


    def set_sort(self, sort_name):
        pass;       LOG and print(f' setting sort: {sort_name}')

        if self.current_sort == sort_name: # switch order
            self.sort_reverse = not self.sort_reverse
        else:
            self.current_sort = sort_name
            self.sort_reverse = False  # back to ascending
        self.update_list_layout()

        # if not present in map -- special value - send as is
        opts = self.get_filtered_opts()
        pass;       LOG and print(f' __ set_sort: opts len: {len(opts)}')
        self.update_list(opts)


    # ignore no change
    def add_opt_change(self, name, scope, val=None):
        """ val=None -- remove option binding for scope
        """
        _old_val = self.optman.get_scope_value(name, scope)
        for i,change in enumerate(self._opt_changes):
            if change.name == name and change.scope == scope:
                del self._opt_changes[i]
                break

        if val is not None:  ### setting value
            if val == _old_val: # no change - ignore
                return
        else:  ### removing value
            if _old_val is None: # no chage - ignore
                return

        lex = ed.get_prop(PROP_LEXER_FILE)  if scope == 'l' else None
        opt_change = OptChange(name,  scope,  val,  lexer=lex,  old_value=_old_val)
        pass;       LOG and print(f'NOTE: new option change: {opt_change}')
        msg_status('Preference: '+format_opt_change(opt_change))
        self._opt_changes.append(opt_change)


    def _fill_tree(self, d, parent=0):
        if parent == 0:
            item_id = tree_proc(self._h_tree, TREE_ITEM_ADD, text=TREE_ITEM_ALL)

        for name,d_ in d.items():
            # add item
            item_id = tree_proc(self._h_tree, TREE_ITEM_ADD, id_item=parent, index=-1, text=name)
            d_['item_id'] = item_id

            items = d_.get('kids')
            if items:
                self._fill_tree(items, parent=item_id)

    def _on_opt_click(self, id_dlg, id_ctl, data='', info=''):
        #print(f'LIST CIKCK: {id_dlg, id_ctl, data, info}')

        _sel_ind = listbox_proc(self._h_list, LISTBOX_GET_SEL)
        self._cur_opt_name = self._list_opt_names[_sel_ind]
        self._cur_opt = self.optman.get_opt(self._cur_opt_name)
        self.edt.set_text_all(self._cur_opt.get('cmt', ''))

        # if have a change for this option -- show it
        removed_scopes = set()
        for opt_change in reversed(self._opt_changes):
            if opt_change.name == self._cur_opt_name:
                if opt_change.value is not None:  # setting value
                    # (scope, val) - [f],[l],[u], [def]
                    active_scoped_val = (opt_change.scope,  opt_change.value)
                    pass;       LOG and print(f'NOTE: using change value: {opt_change}')
                    break
                else: # unsetting option
                    removed_scopes.add(opt_change.scope)
        else: # no matching changes
            #active_scoped_val = self.optman.get_opt_active_value(self._cur_opt, is_ui=False, with_scope=True)
            # skip values that were reset,
            scopes = (scope  for scope in ['f', 'l', 'u', 'def']    if scope not in removed_scopes)
            scoped_vals = ((sc, self.optman.get_opt_scope_value(self._cur_opt, sc, is_ui=False))    for sc in scopes)
            active_scope = next(sc for sc,val in  scoped_vals  if val is not None) # result - is not None
            active_scope_val = self.optman.get_opt_scope_value(self._cur_opt, active_scope, is_ui=True) # for UI
            active_scoped_val = (active_scope, active_scope_val)
            pass;       LOG and print(f' *** using option value: {active_scoped_val}')

        new_scope, _new_val = active_scoped_val

        # set scope
        new_scope_name = self._scope_captions[new_scope]
        with ignore_edit(self.h, self.scope_ed):
            self.scope_ed.set_text_all(new_scope_name)
        self.val_eds.set_type(self.h,  self._cur_opt, scoped_val=active_scoped_val)

    def _on_reset(self, id_dlg, id_ctl, data='', info=''):
        """ remove option for current scope
        """
        _scope_str = self.scope_ed.get_text_all()
        scope = _scope_str[0].lower()  if _scope_str else  ''
        self.add_opt_change(self._cur_opt_name, scope, val=None)

    def on_opt_val_edit(self, id_dlg, id_ctl, data='', info=''):
        ed_name = self.val_eds.get_name(id_ctl)
        prop_type = self._cur_opt['frm']
        pass;       LOG and print(f' + ed name: {ed_name} [{prop_type}]')

        if ed_name == ValueEds.WGT_NAME__EDIT: # str, int, float, -hotk
            key_code, key_state = data
            if key_code != VK_ENTER:
                return
            val = self.val_eds.val_edit.get_text_all()
            if   prop_type == 'int':     val = int(val)
            elif prop_type == 'float':   val = float(val)

        elif ed_name == ValueEds.WGT_NAME__COMBO: # font, int2s, str2s, strs
            val = self.val_eds.val_combo.get_text_all()
            # only accept values from combo-items
            if val not in self.val_eds.val_combo.get_prop(PROP_COMBO_ITEMS):
                pass;       LOG and print(f'NOTE: val not in combo: {val}')
                return

            val = map_option_value(self._cur_opt, caption=val)

        elif ed_name == ValueEds.WGT_NAME__CHECK: # bool
            props = dlg_proc(self.h, DLG_CTL_PROP_GET, index=id_ctl)
            val = props.get('val')
            val = True if val=='1' else  (False if val=='0' else  None)

        elif ed_name == ValueEds.WGT_NAME__BTN_HOTKEY: # hotkey btn
            hotkey = dlg_hotkey(title=self._cur_opt_name)
            val = hotkey

        scope_str = self.scope_ed.get_text_all()
        scope = scope_str[0].lower()  if scope_str else  ''
        self.add_opt_change(self._cur_opt_name, scope, val)


    def _on_scope_change(self, id_dlg, id_ctl, data='', info=''):
        cur_scope_val = self.optman.get_opt_scope_value(self._cur_opt, scope=self.scope, is_ui=False)
        pass;       LOG and print(f' -- scoped val:{self.scope}:[{cur_scope_val}]')

        self.val_eds.set_type(self.h,  self._cur_opt, scoped_val=(self.scope, cur_scope_val))

    def _on_filter(self, id_dlg, id_ctl, data='', info=''):
        if isinstance(data, tuple):     # on_key_down
            key_code, key_state = data
            if key_code == VK_ENTER  and  not key_state:
                _t0 = time.time()
                self.set_filter(self.filter_val)
                _t1 = time.time()
                pass;       LOG and print(f'* set-filter time:{_t1-_t0:.3f}s')

        #else:   # on_change  (typing, pasting)
            #print(f'        . CHANGE')

    def _on_tree_click(self, id_dlg, id_ctl, data='', info=''):
        path = get_tree_path(self._h_tree, item_id=data)
        if path == TREE_ITEM_ALL:  # show all
            self.set_filter('', tree_click=True)
        else:
            self.set_filter('@'+path)

    def _on_header_click(self, id_dlg, id_ctl, data='', info=''):
        pass;       LOG and print(f'--- Header cliock-: {id_dlg, id_ctl, data, info}')
        column_captions, _col_ws = self.columns
        col_ind = data
        self.set_sort(column_captions[col_ind])

    def _on_key(self, id_dlg, id_ctl, data='', info=''):
        key_code = id_ctl
        state = data
        #print(f' on -key:{key_code, state}')

        if key_code == VK_F  and  state == 'c': # Ctrl+F -- show+focus filter
            self.toggle_filter(show=True)
            self._filter_ed.focus()
            return False # consumed

        elif key_code == VK_ESCAPE  and  not state:
            if self._filter_ed.get_prop(PROP_FOCUSED): # <escape> in filter - hide filter
                self.set_filter('')
                self.toggle_filter(show=False)
                return False # consumed

    def listbox_menu(self, id_dlg, id_ctl, data='', info=''):
        if data['y'] < listbox_proc(self._h_list, LISTBOX_GET_ITEM_H): # is header click
            # create menu on first run
            if not self._h_col_menu:
                self._h_col_menu = menu_proc(0, MENU_CREATE)

                for colname in COLS_LIST:
                    la = lambda col=colname: self.on_toggle_col(col)
                    item_id = menu_proc(self._h_col_menu, MENU_ADD, command=la, caption=colname)

                    _enabled = colname != COL_OPT_NAME # 'option name' column - always shown
                    menu_proc(item_id, MENU_SET_ENABLED, command=_enabled)
            #end if

            # update check state
            current_columns, _col_ws = self.columns
            for prop in menu_proc(self._h_col_menu, MENU_ENUM):
                _checked = prop['cap'] in current_columns
                menu_proc(prop['id'], MENU_SET_CHECKED, command=_checked)

            menu_proc(self._h_col_menu, MENU_SHOW)

    def toggle_filter(self, show=False):
        dlg_proc(self.h, DLG_CTL_PROP_SET, name='panel_filter', prop={'vis': show})

        if show == False:  # if hiding filter - reset tree selection to 'All'
            for item_id,name in tree_proc(self._h_tree, TREE_ITEM_ENUM):
                if name == TREE_ITEM_ALL:
                    tree_proc(self._h_tree, TREE_ITEM_SELECT, id_item=item_id)


    def on_toggle_col(self, info):
        pass;       LOG and print(f'NOTE: toggling column: {info}')

        col_cfg = opt_col_cfg[:]

        colname = info
        cur_col_names = [name for name,_w in col_cfg]
        if colname in cur_col_names:  # disableg column
            del opt_col_cfg[cur_col_names.index(colname)]
        else:  # add new column
            new_col_w = 100  if colname != '!' else  19
            opt_col_cfg.append((colname, new_col_w))
            opt_col_cfg.sort(key=lambda item: COLS_LIST.index(item[0]))
        pass;       LOG and print(f' -- new columns: {opt_col_cfg}')

        self.update_list_layout()
        _opts = self.get_filtered_opts()
        self.update_list(_opts)

    def apply_changes(self, closing=False):
        """ batch apply qued option changes
        """
        pass;       LOG and print(f'APPLY_CHANGES')

        if not self._opt_changes  and  not closing:
            msg_status("No option changes has been made")
            return

        for i,change in enumerate(self._opt_changes):
            is_last = i == len(self._opt_changes) - 1
            if change.value is not None: # set value
                self.optman.set_opt(name=change.name,  scope=change.scope,  val=change.value,
                        lexer=change.lexer,  apply_=is_last)
            else: # removing value
                self.optman.reset_opt(name=change.name,  scope=change.scope,
                        lexer=change.lexer,  apply_=is_last)

        self._opt_changes.clear()
        self.optman.on_opts_change()
        _opts = self.get_filtered_opts()
        self.update_list(_opts)

    def dlg_help(self, *args, **vargs):
        if self._h_help == None:
            w, h = 600, 450
            self._h_help = dlg_proc(0, DLG_CREATE)
            dlg_proc(self._h_help, DLG_PROP_SET,
                        prop={'cap': _('Help'),
                            'w': w,
                            'h': h,
                            'resize': True,
                            }
                        )

            n = dlg_proc(self._h_help, DLG_CTL_ADD, 'memo')
            dlg_proc(self._h_help, DLG_CTL_PROP_SET, index=n,
                        prop={
                            'name': 'help_memo',
                            'align': ALIGN_CLIENT,
                            'val': HELP_TEXT,
                            'sp_a':6,
                            }
                        )

        dlg_proc(self._h_help, DLG_SHOW_MODAL)

    def close(self):
        self._save_dlg_cfg()

        dlg_proc(self.h, DLG_HIDE)
        #dlg_proc(self.h, DLG_FREE)


class ValueEds:
    """ * Responsible for: widgets for editing different value formats
        * Formats: bool, float, font, font-e, hotk, int, int2s, str, str2s, strs,
    """
    VALUE_ED_PANEL = 'panel_value'
    VALUE_ED_RESET = 'btn_val_reset'

    WGT_NAME__EDIT       = 'cur_val__edit'
    WGT_NAME__COMBO      = 'cur_val__combo'
    WGT_NAME__CHECK      = 'cur_val__check'

    WGT_NAME__BTN_HOTKEY = 'cur_val__hotkey'

    type_map = {
        'str':      WGT_NAME__EDIT,
        'bool':     WGT_NAME__CHECK,
        'float':    WGT_NAME__EDIT,
        'font':     WGT_NAME__COMBO,
        'font-e':   WGT_NAME__COMBO,
        'hotk':     WGT_NAME__EDIT,
        'int':      WGT_NAME__EDIT,
        'int2s':    WGT_NAME__COMBO,
        'str2s':    WGT_NAME__COMBO,
        'strs':     WGT_NAME__COMBO,
    }

    def __init__(self, val_change_callback):
        self._val_change_callback = val_change_callback
        self._ctl_names = {} # id_ctl -> name
        self._current_type = None
        self.val_edit = None
        self.val_combo = None

        self._ignore_input = False


    def set_type(self, h, opt, scoped_val):
        M = ValueEds

        scope, value = scoped_val

        newtype = opt.get('frm')

        pass;       LOG and print(f'* SET type-value-ed: type:{newtype}, val:{value, scope}')

        self._hide_val_ed(h)

        # unsupported option format
        if newtype not in M.type_map:
            print(f'PreferenesError: unsupported option type: {newtype}')
            return

        # disable option editing?  (some options cannot be a file opt)
        if scope == 'f'  and  not opt['opt'] in FILE_OPTS:
            pass;       LOG and print(f'NOTE: not file option: disabling')
            n = self._wgt_ind(h, M.type_map['str'], show=True) # ~resets wgt props
            self._current_type = 'str'
            dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                    'en': False,
                    'texthint': 'Not available for a file'
                    })
            with ignore_edit(h, self.val_edit):
                self.val_edit.set_text_all('')
            return


        type_wgt_name = M.type_map[newtype]
        # show option-edit widget  and gets widget index
        n = self._wgt_ind(h, type_wgt_name, show=True) # ~resets wgt props

        if newtype == 'str':
            self.val_edit.set_text_all(value or '')

        elif newtype == 'bool':
            dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={'val': value})

        elif newtype == 'float':
            self.val_edit.set_text_all(str(value) or '')

        elif newtype == 'font'  or  newtype == 'font-e': # font-e already has empty value in list
            self.val_combo.set_prop(PROP_COMBO_ITEMS, '\n'.join(opt['lst']))
            with ignore_edit(h, self.val_combo):
                self.val_combo.set_text_all(value)


        elif newtype == 'hotk':
            self.val_edit.set_text_all(value)
            self.val_edit.set_prop(PROP_RO, True)

            ## anchors, hotk btn
            btn_n = self._wgt_ind(h, M.WGT_NAME__BTN_HOTKEY, show=True)
            dlg_proc(h, DLG_CTL_PROP_SET, index=btn_n, prop={
                    'a_l': None,       'a_r': (M.VALUE_ED_RESET, '['),
                    'w': 32, 'max_w': 32, 'sp_l': 2,
            })
            # ... edit
            dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                    'a_l': ('', '['),       'a_r': (M.WGT_NAME__BTN_HOTKEY, '[')
            })

        elif newtype == 'int':
            self.val_edit.set_text_all(str(value))
            self.val_edit.set_prop(PROP_NUMBERS_ONLY, True)

        elif newtype == 'int2s':
            ed_val = map_option_value(opt, val=value)
            with ignore_edit(h, self.val_combo):
                self.val_combo.set_text_all(ed_val)
            self.val_combo.set_prop(PROP_COMBO_ITEMS, '\n'.join(opt['jdc']))

        elif newtype == 'str2s':
            ed_val = map_option_value(opt, val=value)
            with ignore_edit(h, self.val_combo):
                self.val_combo.set_text_all(ed_val)
            self.val_combo.set_prop(PROP_COMBO_ITEMS, '\n'.join(opt['jdc']))

        elif newtype == 'strs':
            with ignore_edit(h, self.val_combo):
                self.val_combo.set_text_all(value)
            self.val_combo.set_prop(PROP_COMBO_ITEMS, '\n'.join(opt['lst']))
        #end if

        self._current_type = newtype

    def get_name(self, id_ctl):
        return self._ctl_names.get(id_ctl)


    def _wgt_ind(self, h, name, show=False):
        """ creates widget if didn't exist
            returns: widget's form index
        """
        M = ValueEds

        default_props = {
            'name': name,
            'p': M.VALUE_ED_PANEL,
            'h': BTN_H, 'max_h': BTN_H,
            'a_l': ('', '['),       'a_r': (M.VALUE_ED_RESET, '['),        'a_t': ('', '['),
            'sp_l': PAD,
            'act': True, 'en': True,
        }

        #TODO validate name
        if name == M.WGT_NAME__EDIT:
            n = dlg_proc(h, DLG_CTL_FIND, prop=name)
            if n == -1:     # add if not already
                n = dlg_proc(h, DLG_CTL_ADD, 'editor_edit')
                h_ed = dlg_proc(h, DLG_CTL_HANDLE, index=n)
                self._ctl_names[n] = name
                self.val_edit = Editor(h_ed)
                if font_size and font_name:
                    self.val_edit.set_prop(PROP_FONT, (font_name, font_size))

            # resetting to defaults
            _props = {**default_props,
                    'on_key_down': self._val_change_callback,
                    'texthint': '',}
            dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop=_props)

            ValueEds.reset_edt(self.val_edit)

        elif name == M.WGT_NAME__COMBO:
            n = dlg_proc(h, DLG_CTL_FIND, prop=name)
            if n == -1:     # add if not already
                n = dlg_proc(h, DLG_CTL_ADD, 'editor_combo')

                _props = {**default_props,   'on_change': self._val_change_callback,}
                dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop=_props)

                h_ed = dlg_proc(h, DLG_CTL_HANDLE, index=n)
                self._ctl_names[n] = name
                self.val_combo = Editor(h_ed)
                self.val_combo.set_prop(PROP_RO, True)
                if font_size and font_name:
                    self.val_combo.set_prop(PROP_FONT, (font_name, font_size))

        elif name == M.WGT_NAME__CHECK:
            n = dlg_proc(h, DLG_CTL_FIND, prop=name)
            if n == -1:     # add if not already
                n = dlg_proc(h, DLG_CTL_ADD, 'check')
                dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                        **default_props,
                        'cap': 'Enable',
                        'act': True,
                        'on_change': self._val_change_callback,
                        'val': '?', # to get thirt state '?' into rotation
                        'font_color': COL_FONT,
                        })
                self._ctl_names[n] = name

        # Extra
        elif name == M.WGT_NAME__BTN_HOTKEY:
            n = dlg_proc(h, DLG_CTL_FIND, prop=name)
            if n == -1:     # add if not already
                n = dlg_proc(h, DLG_CTL_ADD, 'button_ex')
                dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={
                        **default_props,
                        'cap': '...',
                        'on_change': self._val_change_callback,
                        })
                self._ctl_names[n] = name
        #end if

        if show:   # set visible
            dlg_proc(h, DLG_CTL_PROP_SET, index=n, prop={'vis': True})

        return n

    def _hide_val_ed(self, h):
        M = ValueEds

        if not self._current_type:
            return

        to_hide = [M.type_map[self._current_type]]

        if self._current_type == 'hotk':
            to_hide.append(M.WGT_NAME__BTN_HOTKEY)

        for name in to_hide:
            dlg_proc(h, DLG_CTL_PROP_SET, name=name, prop={'vis':False})

    def reset_edt(edt):
        edt.set_prop(PROP_NUMBERS_ONLY, False)
        edt.set_prop(PROP_RO, False)


HELP_TEXT = """About "Filter"
 Suitable options will contain all specified words.
 Tips and tricks:
 • Add "#" to search the words also in comments.
 • Add "@sec" to show options from section with "sec" in name.
   Several sections are allowed.
   Click item in menu "Section..." with Ctrl to add it.
 • To show only overridden options:
   - Add "!"   to show only User+Lexer+File.
   - Add "!!"  to show only Lexer+File
   - Add "!!!" to show only File.
 • Use "<" or ">" for word boundary.
     Example:
       size> <tab
     selects "tab_size" but not "ui_tab_size" or "tab_size_x".

 • Values in table column "!"
     !   option is set in "user.json",
     !!  option is set in "lexer NNN.json",
     !!! option is set for current file,
     L   default value is from "settings_default/lexer NNN.json",
     +   not CudaText standard option.
"""