#!/usr/bin/python

# Copyright (c) 2020, Intel Corporation
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#  * Neither the name of Intel Corporation nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

# extract metrics for cpu from TMAM spreadsheet and generate JSON metrics files
# extract-tmam-metrics.py CPU tmam-csv-file.csv > cpu-metrics.json
from __future__ import print_function
import csv
import argparse
import re
import json
import sys

# metrics redundant with perf or unusable
ignore = set(["MUX", "Power", "Time"])

groups = {
    "IFetch_Line_Utilization": "Frontend",
    "Kernel_Utilization": "Summary",
    "Turbo_Utilization": "Power",
}

# XXX replace with ocperf
event_fixes = (
    ("L1D_PEND_MISS.PENDING_CYCLES,amt1", "cpu@l1d_pend_miss.pending_cycles\\,any=1@"),
    ("MEM_LOAD_UOPS_RETIRED.HIT_LFB_PS", "mem_load_uops_retired.hit_lfb"),
    # uncore hard coded for now for SKX.
    # FIXME for ICX if events are changing
    #SKX:
    ("UNC_M_CAS_COUNT.RD", "uncore_imc@cas_count_read@"),
    ("UNC_M_CAS_COUNT.WR", "uncore_imc@cas_count_write@"),
    ("UNC_CHA_TOR_OCCUPANCY.IA_MISS_DRD:c1", r"cha@event=0x36,umask=0x21,config=0x40433,thresh=1@"),
    ("UNC_CHA_TOR_OCCUPANCY.IA_MISS_DRD", r"cha@event=0x36,umask=0x21,config=0x40433@"),
    ("UNC_CHA_CLOCKTICKS:one_unit", r"cha_0@event=0x0@"),
    ("UNC_CHA_TOR_INSERTS.IA_MISS_DRD", r"cha@event=0x35,umask=0x21,config=0x40433@"),
    ("UNC_M_PMM_RPQ_OCCUPANCY.ALL", r"imc@event=0xe0,umask=0x1@"),
    ("UNC_M_PMM_RPQ_INSERTS", "imc@event=0xe3@"),
    ("UNC_M_PMM_WPQ_INSERTS", "imc@event=0xe7@"),
    ("UNC_M_CLOCKTICKS:one_unit", "imc_0@event=0x0@"),
    # SKL:
    ("UNC_ARB_TRK_OCCUPANCY.DATA_READ:c1", "arb@event=0x80,umask=0x2,cmask=1@"),
    ("UNC_ARB_TRK_OCCUPANCY.DATA_READ", "arb@event=0x80,umask=0x2@"),
    ("UNC_ARB_TRK_REQUESTS.ALL", "arb@event=0x81,umask=0x1@"),
    ("UNC_ARB_COH_TRK_REQUESTS.ALL", "arb@event=0x84,umask=0x1@"),
    # BDX
    ("UNC_C_TOR_OCCUPANCY.MISS_OPCODE:opc=0x182:c1", "cbox@event=0x36,umask=0x3,filter_opc=0x182,thresh=1@"),
    ("UNC_C_TOR_OCCUPANCY.MISS_OPCODE:opc=0x182", "cbox@event=0x36,umask=0x3,filter_opc=0x182@"),
    ("UNC_C_TOR_INSERTS.MISS_OPCODE:opc=0x182:c1", "cbox@event=0x35,umask=0x3,filter_opc=0x182,thresh=1@"),
    ("UNC_C_TOR_INSERTS.MISS_OPCODE:opc=0x182", "cbox@event=0x35,umask=0x3,filter_opc=0x182@"),
    ("UNC_C_CLOCKTICKS:one_unit", "cbox_0@event=0x0@"),


)

# copied from toplev parser. unify?
ratio_column = {
    "IVT": ("IVT", "IVB", "JKT/SNB-EP", "SNB"),
    "IVB": ("IVB", "SNB", ),
    "HSW": ("HSW", "IVB", "SNB", ),
    "HSX": ("HSX", "HSW", "IVT", "IVB", "JKT/SNB-EP", "SNB"),
    "BDW/BDW-DE": ("BDW/BDW-DE", "HSW", "IVB", "SNB", ),
    "BDX": ("BDX", "BDW/BDW-DE", "HSX", "HSW", "IVT", "IVB", "JKT/SNB-EP", "SNB"),
    "SNB": ("SNB", ),
    "JKT/SNB-EP": ("JKT/SNB-EP", "SNB"),
    "SKL/KBL": ("SKL/KBL", "BDW/BDW-DE", "HSW", "IVB", "SNB"),
    "SKX": ("SKX", "SKL/KBL", "BDX", "BDW/BDW-DE", "HSX", "HSW", "IVT", "IVB", "JKT/SNB-EP", "SNB"),
    "KBLR/CFL": ("KBLR/CFL", "SKL/KBL", "BDW/BDW-DE", "HSW", "IVB", "SNB"),
    "CLX": ("CLX", "KBLR/CFL", "SKX", "SKL/KBL", "BDX", "BDW/BDW-DE", "HSX", "HSW", "IVT", "IVB", "JKT/SNB-EP", "SNB"),
}

ap = argparse.ArgumentParser()
ap.add_argument('cpu')
ap.add_argument('csvfile', type=argparse.FileType('r'))
ap.add_argument('--verbose', action='store_true')
ap.add_argument('--memory', action='store_true')
ap.add_argument('--extramodel')
ap.add_argument('--extrajson')
ap.add_argument('--unit')
args = ap.parse_args()

csvf = csv.reader(args.csvfile)

info = []
aux = {}
infoname = {}
nodes = {}
l1nodes = []
for l in csvf:
    if l[0] == 'Key':
        f = {name: ind for name, ind in zip(l, range(len(l)))}
        #print(f)
    def field(x):
        return l[f[x]]

    def find_form():
        if field(args.cpu):
            return field(args.cpu)
        for j in ratio_column[args.cpu]:
            if field(j):
                return field(j)
        return None

    if l[0].startswith("BE") or l[0].startswith("BAD") or l[0].startswith("RET") or l[0].startswith("FE"):
        for j in ("Level1", "Level2", "Level3", "Level4"):
            if field(j):
                form = find_form()
                nodes[field(j)] = form
                if j == "Level1":
                    info.append([field(j), form, field("Metric Description"), "TopdownL1"])
                    infoname[field(j)] = form

    if l[0].startswith("Info"):
        info.append([field("Level1"), find_form(), field("Metric Description"), field("Metric Group")])
        infoname[field("Level1")] = find_form()

    if l[0].startswith("Aux"):
        form = find_form()
        if form == "#NA":
            continue
        aux[field("Level1")] = form
        print("Adding aux", field("Level1"), form, file=sys.stderr)

def bracket(expr):
    if "/" in expr or "*" in expr or "+" in expr or "-" in expr:
        if expr.startswith('(') and expr.endswith(')'):
            return expr
        else:
            return "(" + expr + ")"
    return expr

class SeenEBS(Exception):
    pass

def fixup(form, ebs_mode):
    for j, r in event_fixes:
        def update_fix(x):
            x = x.replace(",", r"\,")
            x = x.replace("=", r"\=")
            return x

        form = form.replace(j, update_fix(r))

    form = re.sub(r":sup", ":u", form)
    form = re.sub(r"\bTSC\b", "msr@tsc@", form)
    form = re.sub(r"\bCLKS\b", "CPU_CLK_UNHALTED.THREAD", form)
    form = form.replace("_PS", "")
    form = form.replace("\b1==1\b", "1")
    form = form.replace("Memory", "1" if args.memory else "0")
    form = re.sub(r'([A-Z0-9_.]+):c(\d+)', r'cpu@\1\\,cmask\\=\2@', form)
    form = form.replace("#(", "(") # XXX hack, shouldn't be needed

    if "#EBS_Mode" in form:
        if ebs_mode == -1:
            raise SeenEBS()

    for i in range(5):
        #  if #Model in ['KBLR' 'CFL' 'CLX'] else
        m = re.match(r'(.*) if #Model in \[(.*)\] else (.*)', form)
        if m:
            if args.extramodel in m.group(2).replace("'", "").split():
                form = m.group(1)
            else:
                form = m.group(3)

        if ebs_mode >= 0:
            m = re.match(r'(.*) if #SMT_on else (.*)', form)
            if m:
                form = m.group(2) if ebs_mode == 0 else m.group(1)

        m = re.match(r'(.*) if #EBS_Mode else (.*)', form)
        if m:
            form = m.group(2) if ebs_mode == 0 else m.group(1)

        m = re.match(r'(.*) if 1 else (.*)', form)
        if m:
            form = m.group(1)
    if "if" in form:
        # print("unhandled if", form, file=sys.stderr)
        index = form.find(' if ')
        form = form[0:index]

    return form

class BadRef(Exception):
    def __init__(self, v):
        self.name = v

def badevent(e):
    if "UNC_CLOCK.SOCKET" in e.upper():
        raise BadRef("UNC_CLOCK.SOCKET")
    if "BASE_FREQUENCY" in e.upper():
        raise BadRef("Base_Frequency")
    if "/Match=" in form:
        raise BadRef("/Match=")

def resolve_all(form, ebs_mode=-1):

    def resolve_aux(v):
        if v == "#Base_Frequency":
            return v
        if v == "#SMT_on":
            return v
        if v == "#DurationTimeInSeconds":
            return "duration_time"
        if v == "#Model":
            return "#Model"
        if v == "#NA":
            return "0"
        if v[1:] in nodes:
            child = nodes[v[1:]]
        else:
            child = aux[v]
        badevent(child)
        child = fixup(child, ebs_mode)
        #print(m.group(0), "=>", child, file=sys.stderr)
        return bracket(child)

    def resolve_info(v):
        if v in infoname:
            return bracket(fixup(infoname[v], ebs_mode))
        elif v in nodes:
            return bracket(fixup(nodes[v], ebs_mode))
        return v

    try:
        # iterate a few times to handle deeper nesting
        for j in range(10):
            form = re.sub(r"#[a-zA-Z0-9_.]+", lambda m: resolve_aux(m.group(0)), form)
            form = re.sub(r"[A-Z_a-z0-9.]+", lambda m: resolve_info(m.group(0)), form)
        badevent(form)
    except BadRef as e:
        print("Skipping " + i[0] + " due to " + e.name, file=sys.stderr)
        return ""

    form = fixup(form, ebs_mode)
    return form

def smt_name(n):
    if n.startswith("SMT"):
        return n
    return n + "_SMT"

def add_sentence(s, n):
    s = s.strip()
    if not s.endswith("."):
        s += "."
    return s + " " + n

jo = []

je = []
if args.extrajson:
    je = json.loads(open(args.extrajson, "r").read())

for i in info:
    if i[0] in ignore:
        print("Skipping", i[0], file=sys.stderr)
        continue

    form = i[1]
    if form is None:
        print("no formula for", i[0], file=sys.stderr)
        continue
    if form == "#NA" or form == "N/A":
        continue
    if args.verbose:
        print(i[0], "orig form", form, file=sys.stderr)

    if i[3] == "":
        if i[0] in groups:
            i[3] = groups[i[0]]

    if i[3] == "Topdown":
        i[3] = "TopDown"

    def save_form(name, group, form, desc, extra=""):
        if form == "":
            return
        if group.endswith(';'):
            group = group.rstrip(';')
        print(name, form, file=sys.stderr)

        j = {
            "MetricName": name,
            "MetricExpr": form,
            "MetricGroup": group,
        }
        if desc.count(".") > 1:
            sdesc = re.sub(r'(?<!i\.e)\. .*', '', desc)
            if extra:
                sdesc = add_sentence(sdesc, extra)
                desc = add_sentence(desc, extra)
            j["BriefDescription"] = sdesc
            if desc != sdesc:
                j["PublicDescription"] = desc
        else:
            j["BriefDescription"] = desc

        if j["MetricName"] == "Page_Walks_Utilization" or j["MetricName"] == "Backend_Bound":
            j["MetricConstraint"] = "NO_NMI_WATCHDOG"

        if j["MetricName"] == "Kernel_Utilization":
            expr = j["MetricExpr"]
            expr = re.sub(r":u", ":k", expr)
            expr = re.sub(r"CPU_CLK_UNHALTED.REF_TSC", "CPU_CLK_UNHALTED.THREAD", expr)
            j["MetricExpr"] = expr

        if args.unit:
            j["Unit"] = args.unit

        jo.append(j)

    try:
        form = resolve_all(form, -1)
        save_form(i[0], i[3], form, i[2])
    except SeenEBS:
        nf = resolve_all(form, 0)
        save_form(i[0], i[3], nf, i[2])
        nf = resolve_all(form, 1)
        save_form(smt_name(i[0]), smt_name(i[3]), nf, i[2],
                  "SMT version; use when SMT is enabled and measuring per logical CPU.")

jo = jo + je

print(json.dumps(jo, indent=4, separators=(',', ': ')))
