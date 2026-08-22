"""语言文字指纹库（GeoGuessr 语言学线索）：特殊字母/字母组合/常见词 → 语言。

依据社区"拉丁语系/日耳曼语族/斯拉夫语族/凯尔特语族/乌拉尔语系等"手册整理：
- chars: 该语言特殊字母（多义字母也列入，靠 unique 区分强度）
- unique: 强独有字母（出现即高度指向该语言，如 ß=德语、þð=冰岛、őű=匈牙利、ħ=马耳他、ə=阿塞拜疆、řůě=捷克、ąęł=波兰、ăâîșț=罗马尼亚、ğşı=土耳其）
- digraphs: 判别字母组合/词尾
- common: 高频虚词/路词（弱佐证）

引擎从 visible_text 扫描字符与组合打分（unique×3 / digraph×2 / chars×1 / 常见词×1），
高分语言 → 支持该语言国家（与 COUNTRY_SEED 的 languages 字段交叉）。
"""
from __future__ import annotations

LANG_CHAR_CLUES: dict[str, dict] = {
    # ---- 罗曼语族 ----
    "Spanish": {"chars": "ñáéíóúü¿¡", "unique": "ñ¿¡", "digraphs": ["ción", "miento", "-dad", "ll-"],
                "common": ["el ", "del ", "los ", "calle", "ruta", "camino", "pueblo", "y "]},
    "French": {"chars": "àâçéèêëîïôùûüÿœ", "unique": "œ", "digraphs": ["l'", "d'", "eau", "oin", "ill", "-ez", "-aux", "-eux"],
               "common": ["rue", "le ", "les ", "un ", "une ", "des ", "et ", "ou ", "sur ", "est ", "sont "]},
    "Italian": {"chars": "àéèìòù", "unique": "", "digraphs": ["zione", "mento", "-tà", "-aggio", "gli", "gn", "sci", "tt", "zz", "cc", "ss", "bb", "pp"],
                "common": ["via ", "è ", "il ", "la ", "di ", "del ", "con ", "non ", "strada", "piazza"]},
    "Catalan": {"chars": "àçéèíïóòúü", "unique": "·", "digraphs": ["l·l", "tx", "tz", "aix", "eix", "-ció", "-tat"],
                "common": ["això", "amb", "mateix", "tots", "que"]},
    "Romanian": {"chars": "ăâîșț", "unique": "ăâîșț", "digraphs": ["-ție", "-țiune", "-escu", "-ului", "-tate"],
                 "common": ["și", "de ", "la ", "cu ", "strada", "bulevardul"]},
    "Portuguese": {"chars": "ãõâêôàçáéíóú", "unique": "ãõ", "digraphs": ["ção", "-dade", "-ismo", "nh", "lh", "ch"],
                   "common": ["rua", "avenida", "não", "uma ", "do ", "da ", "em ", "para "]},
    # ---- 日耳曼语族 ----
    "German": {"chars": "äöüß", "unique": "ß", "digraphs": ["sch", "tsch", "tz", "straße", "-ung", "-chen", "-tät"],
               "common": ["der ", "die ", "das ", "den ", "und ", "ist ", "straße", "strasse", "platz"]},
    "Dutch": {"chars": "àäèéëïöüĳ", "unique": "ĳ", "digraphs": ["ij", "ei", "sch", "oei", "eeuw", "ieuw", "ouw", "-tje", "-lijk", "ge-"],
              "common": ["het ", "op ", "een ", "voor ", "straat", "weg "]},
    "Swedish": {"chars": "åäöé", "unique": "å", "digraphs": ["stj", "skj", "tj", "ck", "-qvist"],
                "common": ["och ", "att ", "det ", "är ", "på ", "gata", "väg"]},
    "Danish": {"chars": "æøå", "unique": "æø", "digraphs": ["øj", "-tion", "-else", "-hed"],
               "common": ["og ", "til ", "på ", "med ", "gade", "vej"]},
    "Norwegian": {"chars": "æøå", "unique": "æø", "digraphs": ["øy", "-sjon", "-else", "-het"],
                  "common": ["og ", "å ", "gate", "vei", "veien"]},
    "Icelandic": {"chars": "áðéíóúýþæö", "unique": "ðþ", "digraphs": ["fj", "gj", "hj", "hv", "kj", "-nn"],
                  "common": ["og ", "til ", "gata", "vegur"]},
    "Faroese": {"chars": "áðíóúýæø", "unique": "ð", "digraphs": ["ggj", "oy", "skt"],
                "common": ["og ", "til ", "vegur"]},
    "Afrikaans": {"chars": "äëïöüê", "unique": "", "digraphs": ["-tjie", "sk"], "common": ["'n ", "as ", "vir ", "nie ", "straat", "weg "]},
    # ---- 波罗的语族 ----
    "Latvian": {"chars": "āčēģīķļņšūž", "unique": "āēģīķļņū", "digraphs": [],
                "common": ["ir ", "bija", "es ", "iela", "ceļš"]},
    "Lithuanian": {"chars": "ąčęėįšųū", "unique": "ąęėįų", "digraphs": [],
                   "common": ["ir ", "yra", "kad", "gatvė", "kelias"]},
    # ---- 斯拉夫语族 ----
    "Polish": {"chars": "ąćęłńóśźż", "unique": "ąęłńśźż", "digraphs": ["rz", "sz", "cz", "prz", "trz"],
               "common": ["ulica", "aleja", "ul ", "w ", "z ", "na ", "jest "]},
    "Czech": {"chars": "áčďéěíňóřšťúůýž", "unique": "řůěďň", "digraphs": [],
              "common": ["ulice", "náměstí", "třída", "je ", "v "]},
    "Slovak": {"chars": "áäčďéíĺľňóôŕšťúýž", "unique": "ĺľŕôä", "digraphs": ["-cia"],
               "common": ["ulica", "námestie", "je ", "v "]},
    "Croatian": {"chars": "čćšžđ", "unique": "ćđ", "digraphs": ["dž", "lj", "nj", "-irati"],
                 "common": ["ulica", "trg", "a ", "i ", "u ", "je "]},
    "Serbian": {"chars": "čćšžđ", "unique": "ćđ", "digraphs": ["dž", "lj", "nj", "-tija", "-ovati"],
                "common": ["ulica", "trg", "a ", "i ", "u ", "je "]},
    # ---- 东斯拉夫语族 ----
    "Russian": {"chars": "ЫЭЁЪыэёъ", "unique": "Ыы", "digraphs": [],
                "common": ["улица", "ул.", "город", "проспект", "набережная", "шоссе"]},
    # ---- 凯尔特语族 ----
    "Welsh": {"chars": "âêîôûŵŷ", "unique": "ŵŷ", "digraphs": ["wy", "ch", "dd", "ff", "ll", "mh", "ngh", "rh", "th", "-ion", "-au", "-wr"],
              "common": ["y ", "yr ", "yn ", "a ", "ac ", "ffordd", "heol", "araf"]},
    "Irish": {"chars": "áéíóú", "unique": "", "digraphs": ["bh", "ch", "dh", "fh", "gh", "mh", "th", "sh", "bp", "dt", "gc"],
              "common": ["sráid", "bóthar", "an ", "na "]},
    "Scottish Gaelic": {"chars": "àèìòù", "unique": "", "digraphs": ["bh", "ch", "dh", "fh", "gh", "mh", "th", "sh", "sg", "chd"],
                        "common": ["sràid", "ratha", "an ", "na "]},
    # ---- 乌拉尔语系 ----
    "Finnish": {"chars": "åäö", "unique": "å", "digraphs": ["ää", "-nen", "-kä"],
                "common": ["katu", "tie ", "on ", "sinä", "ja "]},
    "Estonian": {"chars": "õäöü", "unique": "õ", "digraphs": ["õõ", "üü", "hh", "öö"],
                 "common": ["tänav", "tee ", "ja ", "on ", "ei ", "ta "]},
    "Hungarian": {"chars": "áéíóöőúüű", "unique": "őű", "digraphs": ["cs", "gy", "ly", "ny", "sz", "ty", "zs", "leg-", "-obb"],
                  "common": ["utca", "út ", "és ", "van ", "hogy ", "a ", "az "]},
    # ---- 其他 ----
    "Turkish": {"chars": "çğıöşü", "unique": "ğış", "digraphs": [],
                "common": ["cadde", "sokak", "dur ", "ve ", "bir "]},
    "Indonesian": {"chars": "", "unique": "", "digraphs": ["memper", "-kan", "-nya"],
                   "common": ["jalan", "jln", "dan ", "di ", "ke ", "yang ", "awas",
                              "berhenti", "televisi"]},
    "Albanian": {"chars": "ëç", "unique": "ë", "digraphs": ["dh", "gj", "ll", "nj", "rr", "sh", "th", "xh", "zh"],
                 "common": ["rruga", "dhe ", "i ", "të ", "me ", "po ", "jo "]},
    "Maltese": {"chars": "ċġħġż", "unique": "ħġċ", "digraphs": ["għ"],
                "common": ["triq", "il-", "u ", "ta' "]},
    "Greenlandic": {"chars": "", "unique": "", "digraphs": ["qq", "aa", "ii", "uu"],
                    "common": ["a ", "i ", "u ", "eqqa"]},
    "Vietnamese": {"chars": "ăâđêôơư", "unique": "ăâđơư", "digraphs": ["ng", "ngh", "nh"],
                   "common": ["đường", "phố", "cái ", "không", "có ", "và ", "tại ", "với "]},
    "Azerbaijani": {"chars": "əçğıöşü", "unique": "ə", "digraphs": [],
                    "common": ["küçə", "prospekt", "və ", "bir "]},
}
