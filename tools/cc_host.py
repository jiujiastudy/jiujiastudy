"""认学校：域名规范化、按校名查 Canvas 地址、不带 token 探测是不是 Canvas。

没有默认学校。SCHOOLS 是校名 → 地址的表，用户说了校名才查；表里每个地址 2026-09-17 都不带 token
探过（/api/v1/users/self 回 Canvas 的 401）。查不到、对得上好几所，就问用户，不猜：
token 只发给查表查准的那一个地址，或者用户自己发来的网址。
"""
import re
import unicodedata
import urllib.error
import urllib.parse

import canvas_api

# (地址, 给人看的名字, 别名)。别名按 _norm 整句比较：大小写、空格、标点都不算。
# 同一个别名故意出现在两所学校（纽卡斯尔、UVA）时算「对得上好几所」，要用户说全名。
SCHOOLS = [
    # 澳洲
    ("https://canvas.sydney.edu.au", "悉尼大学（University of Sydney）",
     ("悉尼大学", "悉大", "usyd", "university of sydney", "sydney uni", "sydney university", "sydney")),
    ("https://canvas.lms.unimelb.edu.au", "墨尔本大学（University of Melbourne）",
     ("墨尔本大学", "墨大", "unimelb", "university of melbourne", "melbourne uni", "melbourne university", "melbourne")),
    ("https://canvas.uts.edu.au", "悉尼科技大学（UTS）", ("悉尼科技大学", "悉尼科大", "uts", "university of technology sydney")),
    ("https://myuni.adelaide.edu.au", "阿德莱德大学（Adelaide）",
     ("阿德莱德大学", "阿德", "阿大", "university of adelaide", "adelaide university", "adelaide uni", "adelaide")),
    ("https://rmit.instructure.com", "皇家墨尔本理工大学（RMIT）", ("皇家墨尔本理工大学", "皇家墨尔本理工", "rmit", "rmit university")),
    ("https://canvas.qut.edu.au", "昆士兰科技大学（QUT）", ("昆士兰科技大学", "昆士兰科大", "qut", "queensland university of technology")),
    ("https://canvas.newcastle.edu.au", "纽卡斯尔大学（澳洲，University of Newcastle）",
     ("纽卡斯尔大学", "纽卡斯尔", "纽卡", "澳洲纽卡斯尔大学", "澳大利亚纽卡斯尔大学", "uon", "university of newcastle", "newcastle")),
    ("https://canvas.flinders.edu.au", "弗林德斯大学（Flinders）", ("弗林德斯大学", "弗林德斯", "flinders", "flinders university")),
    ("https://swinburne.instructure.com", "斯威本科技大学（Swinburne）",
     ("斯威本科技大学", "斯威本", "swinburne", "swinburne university of technology")),
    ("https://canvas.anu.edu.au", "澳大利亚国立大学（ANU）", ("澳大利亚国立大学", "澳洲国立大学", "澳国立", "anu", "australian national university")),
    # 新西兰
    ("https://canvas.auckland.ac.nz", "奥克兰大学（University of Auckland）",
     ("奥克兰大学", "university of auckland", "auckland uni", "auckland")),
    ("https://canvas.aut.ac.nz", "奥克兰理工大学（AUT）", ("奥克兰理工大学", "奥克兰理工", "aut", "auckland university of technology")),
    ("https://nuku.wgtn.ac.nz", "惠灵顿维多利亚大学（Victoria University of Wellington）",
     ("惠灵顿维多利亚大学", "vuw", "victoria university of wellington", "te herenga waka")),
    # 英国
    ("https://canvas.ox.ac.uk", "牛津大学（Oxford）", ("牛津大学", "牛津", "university of oxford", "oxford university", "oxford")),
    ("https://canvas.bham.ac.uk", "伯明翰大学（Birmingham）", ("伯明翰大学", "伯大", "university of birmingham", "birmingham")),
    ("https://ncl.instructure.com", "纽卡斯尔大学（英国，Newcastle University）",
     ("纽卡斯尔大学", "纽卡斯尔", "纽卡", "英国纽卡斯尔大学", "newcastle university", "newcastle")),
    ("https://canvas.manchester.ac.uk", "曼彻斯特大学（Manchester）", ("曼彻斯特大学", "曼大", "曼彻斯特", "university of manchester", "manchester")),
    ("https://canvas.liverpool.ac.uk", "利物浦大学（Liverpool）", ("利物浦大学", "university of liverpool", "liverpool")),
    ("https://canvas.sussex.ac.uk", "萨塞克斯大学（Sussex）", ("萨塞克斯大学", "苏塞克斯大学", "萨塞克斯", "苏塞克斯", "university of sussex", "sussex")),
    ("https://canvas.qub.ac.uk", "贝尔法斯特女王大学（Queen's University Belfast）",
     ("贝尔法斯特女王大学", "qub", "queen's university belfast", "queens university belfast")),
    ("https://canvas.hw.ac.uk", "赫瑞瓦特大学（Heriot-Watt）", ("赫瑞瓦特大学", "赫瑞瓦特", "heriot-watt", "heriot-watt university")),
    ("https://canvas.stir.ac.uk", "斯特灵大学（Stirling）", ("斯特灵大学", "斯特林大学", "university of stirling", "stirling")),
    ("https://canvas.imperial.ac.uk", "帝国理工学院（Imperial College London）",
     ("帝国理工学院", "帝国理工", "帝国理工大学", "imperial", "imperial college", "imperial college london")),
    # 美国
    ("https://courseworks2.columbia.edu", "哥伦比亚大学（Columbia）", ("哥伦比亚大学", "哥大", "columbia", "columbia university")),
    ("https://bruinlearn.ucla.edu", "加州大学洛杉矶分校（UCLA）", ("加州大学洛杉矶分校", "ucla")),
    ("https://bcourses.berkeley.edu", "加州大学伯克利分校（UC Berkeley）", ("加州大学伯克利分校", "伯克利", "uc berkeley", "berkeley")),
    ("https://canvas.ucsd.edu", "加州大学圣地亚哥分校（UCSD）", ("加州大学圣地亚哥分校", "ucsd", "uc san diego")),
    ("https://canvas.ucdavis.edu", "加州大学戴维斯分校（UC Davis）", ("加州大学戴维斯分校", "uc davis")),
    ("https://canvas.eee.uci.edu", "加州大学尔湾分校（UC Irvine）", ("加州大学尔湾分校", "加州大学欧文分校", "uci", "uc irvine")),
    ("https://canvas.ucsc.edu", "加州大学圣克鲁兹分校（UC Santa Cruz）", ("加州大学圣克鲁兹分校", "ucsc", "uc santa cruz")),
    ("https://elearn.ucr.edu", "加州大学河滨分校（UC Riverside）", ("加州大学河滨分校", "ucr", "uc riverside")),
    ("https://canvas.illinois.edu", "伊利诺伊大学厄巴纳-香槟分校（UIUC）",
     ("伊利诺伊大学厄巴纳-香槟分校", "伊利诺伊大学香槟分校", "uiuc", "university of illinois urbana-champaign")),
    ("https://canvas.uw.edu", "华盛顿大学（西雅图，University of Washington）", ("华盛顿大学", "university of washington", "uw seattle")),
    ("https://umich.instructure.com", "密歇根大学（University of Michigan）",
     ("密歇根大学", "密西根大学", "密歇根大学安娜堡分校", "umich", "university of michigan")),
    ("https://canvas.cmu.edu", "卡内基梅隆大学（CMU）", ("卡内基梅隆大学", "卡耐基梅隆大学", "cmu", "carnegie mellon", "carnegie mellon university")),
    ("https://canvas.harvard.edu", "哈佛大学（Harvard）", ("哈佛大学", "哈佛", "harvard", "harvard university")),
    ("https://canvas.stanford.edu", "斯坦福大学（Stanford）", ("斯坦福大学", "斯坦福", "stanford", "stanford university")),
    ("https://canvas.upenn.edu", "宾夕法尼亚大学（UPenn）", ("宾夕法尼亚大学", "宾大", "upenn", "university of pennsylvania")),
    ("https://canvas.cornell.edu", "康奈尔大学（Cornell）", ("康奈尔大学", "康奈尔", "cornell", "cornell university")),
    ("https://canvas.northwestern.edu", "西北大学（美国，Northwestern）", ("美国西北大学", "northwestern", "northwestern university")),
    ("https://canvas.uchicago.edu", "芝加哥大学（UChicago）", ("芝加哥大学", "芝大", "uchicago", "university of chicago")),
    ("https://canvas.duke.edu", "杜克大学（Duke）", ("杜克大学", "duke", "duke university")),
    ("https://canvas.wisc.edu", "威斯康星大学麦迪逊分校（UW-Madison）", ("威斯康星大学麦迪逊分校", "uw-madison", "university of wisconsin-madison")),
    ("https://canvas.umn.edu", "明尼苏达大学（UMN）", ("明尼苏达大学", "明尼苏达大学双城分校", "umn", "university of minnesota")),
    ("https://psu.instructure.com", "宾夕法尼亚州立大学（Penn State）",
     ("宾夕法尼亚州立大学", "宾州州立大学", "宾州州立", "penn state", "pennsylvania state university")),
    ("https://utexas.instructure.com", "德克萨斯大学奥斯汀分校（UT Austin）", ("德克萨斯大学奥斯汀分校", "德州大学奥斯汀分校", "ut austin", "utexas")),
    ("https://canvas.brown.edu", "布朗大学（Brown）", ("布朗大学", "brown university")),
    ("https://canvas.mit.edu", "麻省理工学院（MIT）", ("麻省理工学院", "麻省理工", "mit")),
    ("https://wustl.instructure.com", "圣路易斯华盛顿大学（WashU）", ("圣路易斯华盛顿大学", "washu", "wustl", "washington university in st. louis")),
    ("https://canvas.emory.edu", "埃默里大学（Emory）", ("埃默里大学", "emory", "emory university")),
    ("https://canvas.rice.edu", "莱斯大学（Rice）", ("莱斯大学", "rice university")),
    ("https://canvas.nd.edu", "圣母大学（Notre Dame）", ("圣母大学", "notre dame", "university of notre dame")),
    ("https://canvas.tufts.edu", "塔夫茨大学（Tufts）", ("塔夫茨大学", "tufts", "tufts university")),
    ("https://canvas.asu.edu", "亚利桑那州立大学（ASU）", ("亚利桑那州立大学", "asu", "arizona state university")),
    ("https://ufl.instructure.com", "佛罗里达大学（UF）", ("佛罗里达大学", "ufl", "university of florida")),
    ("https://uiowa.instructure.com", "爱荷华大学（University of Iowa）", ("爱荷华大学", "艾奥瓦大学", "uiowa", "university of iowa")),
    ("https://canvas.its.virginia.edu", "弗吉尼亚大学（UVA）", ("弗吉尼亚大学", "uva", "university of virginia")),
    ("https://wsu.instructure.com", "华盛顿州立大学（Washington State）", ("华盛顿州立大学", "washington state university")),
    ("https://canvas.colorado.edu", "科罗拉多大学博尔德分校（CU Boulder）", ("科罗拉多大学博尔德分校", "cu boulder", "university of colorado boulder")),
    ("https://utah.instructure.com", "犹他大学（University of Utah）", ("犹他大学", "university of utah")),
    ("https://templeu.instructure.com", "天普大学（Temple）", ("天普大学", "temple university")),
    ("https://canvas.wpi.edu", "伍斯特理工学院（WPI）", ("伍斯特理工学院", "wpi", "worcester polytechnic institute")),
    ("https://sit.instructure.com", "史蒂文斯理工学院（Stevens）", ("史蒂文斯理工学院", "stevens institute of technology")),
    ("https://canvas.case.edu", "凯斯西储大学（CWRU）", ("凯斯西储大学", "cwru", "case western reserve university")),
    ("https://canvas.pitt.edu", "匹兹堡大学（Pitt）", ("匹兹堡大学", "pitt", "university of pittsburgh")),
    # 加拿大
    ("https://q.utoronto.ca", "多伦多大学（UofT）", ("多伦多大学", "多大", "uoft", "utoronto", "university of toronto")),
    ("https://canvas.ubc.ca", "英属哥伦比亚大学（UBC）", ("英属哥伦比亚大学", "ubc", "university of british columbia")),
    ("https://canvas.sfu.ca", "西蒙菲莎大学（SFU）", ("西蒙菲莎大学", "西门菲沙大学", "sfu", "simon fraser university")),
    # 香港、新加坡
    ("https://canvas.ust.hk", "香港科技大学（HKUST）", ("香港科技大学", "港科大", "hkust")),
    ("https://canvas.cityu.edu.hk", "香港城市大学（CityU）", ("香港城市大学", "港城大", "cityu", "city university of hong kong")),
    ("https://canvas.polyu.edu.hk", "香港理工大学（PolyU）", ("香港理工大学", "港理工", "polyu", "hong kong polytechnic university")),
    ("https://canvas.nus.edu.sg", "新加坡国立大学（NUS）", ("新加坡国立大学", "新国大", "nus", "national university of singapore")),
    # 欧洲
    ("https://canvas.uva.nl", "阿姆斯特丹大学（UvA）", ("阿姆斯特丹大学", "uva", "university of amsterdam")),
    ("https://canvas.eur.nl", "鹿特丹伊拉斯姆斯大学（Erasmus）", ("鹿特丹伊拉斯姆斯大学", "伊拉斯姆斯大学", "erasmus university rotterdam")),
    ("https://tilburguniversity.instructure.com", "蒂尔堡大学（Tilburg）", ("蒂尔堡大学", "tilburg", "tilburg university")),
    ("https://canvas.maastrichtuniversity.nl", "马斯特里赫特大学（Maastricht）", ("马斯特里赫特大学", "maastricht", "maastricht university")),
    ("https://canvas.kth.se", "瑞典皇家理工学院（KTH）", ("瑞典皇家理工学院", "kth", "kth royal institute of technology")),
    ("https://canvas.education.lu.se", "隆德大学（Lund）", ("隆德大学", "lund", "lund university")),
]


def normalize_host(url):
    """登录页 / 课程页网址 → scheme://域名。"""
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u):
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    return f"{p.scheme}://{p.netloc}" if p.netloc else ""


def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").strip().lower()
    s = re.sub(r"^(我是|我在|我读|在)", "", s)
    s = re.sub(r"(的学生|学生|的)$", "", s)
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[\W_]+", "", s)


def looks_like_url(text):
    t = (text or "").strip()
    return bool(re.match(r"^https?://", t, re.I) or re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", t, re.I))


def resolve_school(text):
    """用户说的校名或网址 → {"host", "name"} / {"ambiguous": [(host, name)…]} / {}（没认出）。

    网址直接用。校名只整句对别名，不做「包含」或「开头是」：「西悉尼大学」包含「悉尼大学」，
    「伊利诺伊大学芝加哥分校」以「伊利诺伊大学」开头，都是另一所学校，猜错了 token 就发错了地方。
    """
    if looks_like_url(text):
        host = normalize_host(text)
        return {"host": host, "name": None} if host else {}
    key = _norm(text)
    if not key:
        return {}
    hits = {host: name for host, name, aliases in SCHOOLS if any(_norm(a) == key for a in aliases)}
    if len(hits) == 1:
        host, name = next(iter(hits.items()))
        return {"host": host, "name": name}
    if hits:
        return {"ambiguous": sorted(hits.items(), key=lambda x: x[1])}
    return {}


def is_canvas(host):
    """不带 token 探一下：标准 Canvas 对 /api/v1/users/self 回 401；200 是普通网页；404 / HTML 不是。连不上返回 None。"""
    try:
        canvas_api.Canvas(host, None, timeout=15, retries=0).fetch(host + "/api/v1/users/self")
        return False
    except urllib.error.HTTPError as e:
        return e.code == 401
    except (urllib.error.URLError, OSError, ValueError):
        return None
