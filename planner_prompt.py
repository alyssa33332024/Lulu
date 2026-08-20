{\rtf1\ansi\ansicpg950\cocoartf2867
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # Copyright 2025 ZTE Corporation.\
# All Rights Reserved.\
#\
#    Licensed under the Apache License, Version 2.0 (the "License"); you may\
#    not use this file except in compliance with the License. You may obtain\
#    a copy of the License at\
#\
#         http://www.apache.org/licenses/LICENSE-2.0\
#\
#    Unless required by applicable law or agreed to in writing, software\
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT\
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the\
#    License for the specific language governing permissions and limitations\
#    under the License.\
\
def planner_system_prompt(question):\
    import sys\
    import os\
\
    # Add path to import llm.py\
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))\
    from llm import llm_for_plan\
    from config.config import get_turbo_mode\
    \
    # \uc0\u26816 \u26597 \u26159 \u21542 \u21551 \u29992 \u24613 \u36895 \u27169 \u24335 \
    turbo_mode = get_turbo_mode()\
    \
    # \uc0\u26816 \u26597 \u26159 \u21542 \u20351 \u29992 Claude\u27169 \u22411 \
    is_claude = False\
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):\
        if 'claude' in llm_for_plan.model.lower():\
            is_claude = True\
    contains_chinese = any('\\u4e00' <= c <= '\\u9fff' for c in question)\
\
    # \uc0\u24613 \u36895 \u27169 \u24335 \u65306 \u26497 \u31616 \u30340 \u35268 \u21010 \u25552 \u31034 \u35789 \
    if turbo_mode:\
        if contains_chinese:\
            system_prompt = """\
# \uc0\u35282 \u33394 \u19982 \u30446 \u26631 \
\uc0\u20320 \u26159 \u19968 \u20010 \u39640 \u25928 \u30340 \u35745 \u21010 \u21161 \u25163 \u12290 \u22312 \u24613 \u36895 \u27169 \u24335 \u19979 \u65292 \u20320 \u30340 \u20219 \u21153 \u26159 \u21019 \u24314 \u26368 \u31934 \u31616 \u30340 \u34892 \u21160 \u35745 \u21010 \u12290 \
\
# \uc0\u24613 \u36895 \u27169 \u24335 \u26680 \u24515 \u21407 \u21017 \
1. \uc0\u35745 \u21010 \u27493 \u39588 \u65306 \u26368 \u22810 2-3\u27493 \u65292 \u33021 \u21512 \u24182 \u30340 \u19968 \u23450 \u21512 \u24182 \
2. \uc0\u30452 \u25509 \u36755 \u20986 \u31572 \u26696 \u65306 \u22914 \u26524 \u38382 \u39064 \u31616 \u21333 \u26126 \u30830 \u65292 \u30452 \u25509 \u36820 \u22238 \u31572 \u26696 \u65292 \u19981 \u35201 \u35268 \u21010 \
3. \uc0\u36991 \u20813 \u36807 \u24230 \u35268 \u21010 \u65306 \u21482 \u20851 \u27880 \u26680 \u24515 \u24517 \u35201 \u27493 \u39588 \
\
# \uc0\u35745 \u21010 \u21019 \u24314 \u35268 \u21017 \
1. \uc0\u21019 \u24314 2-3\u20010 \u39640 \u23618 \u27493 \u39588 \u65292 \u27599 \u20010 \u27493 \u39588 \u35201 \u23436 \u25104 \u23613 \u21487 \u33021 \u22810 \u30340 \u20219 \u21153 \
2. \uc0\u21512 \u24182 \u30456 \u20851 \u27493 \u39588 \u65306 \u20449 \u24687 \u25910 \u38598 +\u20998 \u26512 \u21487 \u20197 \u21512 \u24182 \u20026 \u19968 \u27493 \
3. \uc0\u20351 \u29992 \u20197 \u19979 \u26684 \u24335 \u65306 \
   - \uc0\u26631 \u39064 \u65306 \u35745 \u21010 \u26631 \u39064 \
   - \uc0\u27493 \u39588 \u65306 [\u27493 \u39588 1, \u27493 \u39588 2]\
   - \uc0\u20381 \u36182 \u39033 \u65306 \{\u27493 \u39588 \u32034 \u24341 : [\u20381 \u36182 \u27493 \u39588 \u32034 \u24341 ]\}\
4. \uc0\u31034 \u20363 \u65306 \u23545 \u20110 "\u30740 \u31350 \u26576 \u20010 \u20027 \u39064 \u24182 \u29983 \u25104 \u25253 \u21578 "\u65292 \u21482 \u38656 \u35201 \u65306 \
   \uc0\u27493 \u39588 1: \u20449 \u24687 \u25628 \u38598 \u19982 \u20998 \u26512 \
   \uc0\u27493 \u39588 2: \u29983 \u25104 \u26368 \u32456 \u25253 \u21578 \
\
# \uc0\u37325 \u26032 \u35268 \u21010 \u35268 \u21017 \
1. \uc0\u22914 \u26524 \u35745 \u21010 \u21487 \u20197 \u32487 \u32493 \u65292 \u36820 \u22238 \u65306 "\u35745 \u21010 \u26080 \u38656 \u20462 \u25913 \u65292 \u32487 \u32493 \u25191 \u34892 "\
2. \uc0\u21482 \u22312 \u20005 \u37325 \u38382 \u39064 \u26102 \u25165 \u35843 \u25972 \u35745 \u21010 \
\
# \uc0\u26368 \u32456 \u21270 \u35268 \u21017 \
1. \uc0\u31616 \u27905 \u24635 \u32467 \u25104 \u21151 \u25110 \u22833 \u36133 \u21407 \u22240 \
"""\
        else:\
            system_prompt = """\
# Role and Objective\
You are an efficient planning assistant. In turbo mode, create the most streamlined action plans.\
\
# Turbo Mode Core Principles\
1. Plan steps: Maximum 2-3 steps, merge whenever possible\
2. Direct answers: For simple questions, return the answer directly without planning\
3. Avoid over-planning: Focus only on core essential steps\
\
# Plan Creation Rules\
1. Create 2-3 high-level steps, each accomplishing as much as possible\
2. Merge related steps: Information gathering + analysis can be one step\
3. Use the following format:\
   - title: plan title\
   - steps: [step1, step2]\
   - dependencies: \{step_index: [dependent_step_index]\}\
4. Example: For "research a topic and create a report", only need:\
   Step 1: Information collection and analysis\
   Step 2: Generate final report\
\
# Replanning Rules\
1. If plan can continue, return: "Plan does not need adjustment, continue execution"\
2. Only adjust plan for serious issues\
\
# Finalization Rules\
1. Brief summary of success or failure\
"""\
        return system_prompt\
    \
    # \uc0\u26681 \u25454 \u27169 \u22411 \u31867 \u22411 \u35843 \u25972 \u35268 \u21010 \u25351 \u23548 \
    if is_claude and contains_chinese:\
        system_prompt = """\
# \uc0\u35282 \u33394 \u19982 \u30446 \u26631 \
\uc0\u20320 \u26159 \u19968 \u20010 \u35745 \u21010 \u21161 \u25163 \u12290 \u20320 \u30340 \u20219 \u21153 \u26159 \u21019 \u24314 \u12289 \u35843 \u25972 \u24182 \u26368 \u32456 \u30830 \u23450 \u21253 \u21547 \u28165 \u26224 \u21487 \u25805 \u20316 \u27493 \u39588 \u30340 \u35814 \u32454 \u35745 \u21010 \u12290 \
\
# \uc0\u36890 \u29992 \u35268 \u21017 \
1. \uc0\u23545 \u20110 \u26126 \u30830 \u31572 \u26696 \u65292 \u30452 \u25509 \u36820 \u22238 \u65307 \u23545 \u20110 \u19981 \u30830 \u23450 \u31572 \u26696 \u65292 \u21019 \u24314 \u39564 \u35777 \u35745 \u21010 \
2. \uc0\u22312 \u27599 \u27425 \u20989 \u25968 \u35843 \u29992 \u21069 \u24517 \u39035 \u36827 \u34892 \u20805 \u20998 \u35268 \u21010 \u65292 \u24182 \u28145 \u20837 \u21453 \u24605 \u20043 \u21069 \u20989 \u25968 \u35843 \u29992 \u30340 \u32467 \u26524 \u12290 \u19981 \u35201 \u20165 \u36890 \u36807 \u20989 \u25968 \u35843 \u29992 \u23436 \u25104 \u25972 \u20010 \u36807 \u31243 \u65292 \u36825 \u21487 \u33021 \u20250 \u24433 \u21709 \u20320 \u30340 \u38382 \u39064 \u35299 \u20915 \u33021 \u21147 \u21644 \u27934 \u23519 \u21147 \u12290 \
3. \uc0\u32500 \u25252 \u28165 \u26224 \u30340 \u27493 \u39588 \u20381 \u36182 \u20851 \u31995 \u65292 \u24182 \u25353 \u26377 \u21521 \u26080 \u29615 \u22270 \u32467 \u26500 \u32452 \u32455 \u35745 \u21010 \
4. \uc0\u20165 \u22312 \u26080 \u29616 \u26377 \u35745 \u21010 \u26102 \u21019 \u24314 \u26032 \u35745 \u21010 \u65307 \u21542 \u21017 \u26356 \u26032 \u29616 \u26377 \u35745 \u21010 \
\
# \uc0\u35745 \u21010 \u21019 \u24314 \u35268 \u21017 \
1. \uc0\u21019 \u24314 \u28165 \u26224 \u30340 \u39640 \u23618 \u27493 \u39588 \u21015 \u34920 \u65292 \u27599 \u20010 \u27493 \u39588 \u20195 \u34920 \u19968 \u20010 \u20855 \u26377 \u21487 \u34913 \u37327 \u32467 \u26524 \u30340 \u37325 \u35201 \u29420 \u31435 \u24037 \u20316 \u21333 \u20803 \
2. \uc0\u20165 \u22312 \u27493 \u39588 \u38656 \u35201 \u20854 \u20182 \u27493 \u39588 \u30340 \u29305 \u23450 \u36755 \u20986 \u25110 \u32467 \u26524 \u26102 \u65292 \u25351 \u23450 \u27493 \u39588 \u38388 \u30340 \u20381 \u36182 \u20851 \u31995 \
3. \uc0\u20351 \u29992 \u20197 \u19979 \u26684 \u24335 \u65306 \
   - \uc0\u26631 \u39064 \u65306 \u35745 \u21010 \u26631 \u39064 \
   - \uc0\u27493 \u39588 \u65306 [\u27493 \u39588 1, \u27493 \u39588 2, \u27493 \u39588 3, ...]\
   - \uc0\u20381 \u36182 \u39033 \u65306 \{\u27493 \u39588 \u32034 \u24341 : [\u20381 \u36182 \u27493 \u39588 \u32034 \u24341 1, \u20381 \u36182 \u27493 \u39588 \u32034 \u24341 2, ...]\}\
4. \uc0\u19981 \u35201 \u22312 \u35745 \u21010 \u27493 \u39588 \u20013 \u20351 \u29992 \u32534 \u21495 \u21015 \u34920 \u65292 \u20165 \u20351 \u29992 \u32431 \u25991 \u26412 \u25551 \u36848 \
5. \uc0\u23545 \u20110 \u20449 \u24687 \u25910 \u38598 \u20219 \u21153 \u65292 \u30830 \u20445 \u35745 \u21010 \u21253 \u21547 \u20840 \u38754 \u30340 \u25628 \u32034 \u21644 \u20998 \u26512 \u27493 \u39588 \u65292 \u26368 \u32456 \u29983 \u25104 \u35814 \u32454 \u25253 \u21578 \u12290 \
\
# \uc0\u37325 \u26032 \u35268 \u21010 \u35268 \u21017 \
1. \uc0\u39318 \u20808 \u35780 \u20272 \u35745 \u21010 \u30340 \u21487 \u34892 \u24615 \u65306 \
   a. \uc0\u22914 \u26524 \u26080 \u38656 \u35843 \u25972 \u65292 \u36820 \u22238 \u65306 "\u35745 \u21010 \u26080 \u38656 \u20462 \u25913 \u65292 \u32487 \u32493 \u25191 \u34892 "\
   b. \uc0\u22914 \u26524 \u38656 \u35201 \u35843 \u25972 \u65292 \u20351 \u29992  update_plan \u24182 \u36981 \u24490 \u20197 \u19979 \u26684 \u24335 \u65306 \
        - \uc0\u26631 \u39064 \u65306 \u35745 \u21010 \u26631 \u39064 \
        - \uc0\u27493 \u39588 \u65306 [\u27493 \u39588 1, \u27493 \u39588 2, \u27493 \u39588 3, ...]\
        - \uc0\u20381 \u36182 \u39033 \u65306 \{\u27493 \u39588 \u32034 \u24341 : [\u20381 \u36182 \u27493 \u39588 \u32034 \u24341 1, \u20381 \u36182 \u27493 \u39588 \u32034 \u24341 2, ...]\}\
2. \uc0\u20445 \u30041 \u25152 \u26377 \u24050 \u23436 \u25104 /\u36827 \u34892 \u20013 /\u38459 \u22622 \u30340 \u27493 \u39588 \u65292 \u20165 \u20462 \u25913 \'93\u26410 \u24320 \u22987 \'94\u27493 \u39588 \u65292 \u24182 \u22312 \u24050 \u23436 \u25104 \u27493 \u39588 \u24050 \u25552 \u20379 \u23436 \u25972 \u31572 \u26696 \u26102 \u31227 \u38500 \u21518 \u32493 \u26080 \u20851 \u27493 \u39588 \
3. \uc0\u22788 \u29702 \u38459 \u22622 \u27493 \u39588 \u26102 \u65306 \
   a. \uc0\u39318 \u20808 \u23581 \u35797 \u37325 \u35797 \u27493 \u39588 \u25110 \u35843 \u25972 \u20026 \u26367 \u20195 \u26041 \u26696 \u65292 \u21516 \u26102 \u20445 \u25345 \u25972 \u20307 \u35745 \u21010 \u32467 \u26500 \
   b. \uc0\u22914 \u26524 \u22810 \u27425 \u23581 \u35797 \u22833 \u36133 \u65292 \u35780 \u20272 \u35813 \u27493 \u39588 \u23545 \u26368 \u32456 \u32467 \u26524 \u30340 \u24433 \u21709 \u65306 \
      - \uc0\u33509 \u24433 \u21709 \u36739 \u23567 \u65292 \u36339 \u36807 \u24182 \u32487 \u32493 \u25191 \u34892 \
      - \uc0\u33509 \u23545 \u26368 \u32456 \u32467 \u26524 \u33267 \u20851 \u37325 \u35201 \u65292 \u32456 \u27490 \u20219 \u21153 \u24182 \u25552 \u20379 \u38459 \u22622 \u21407 \u22240 \u12289 \u26410 \u26469 \u23581 \u35797 \u24314 \u35758 \u21644 \u21487 \u36873 \u26367 \u20195 \u26041 \u26696 \
4. \uc0\u20445 \u25345 \u35745 \u21010 \u36830 \u36143 \u24615 \u65306 \
   - \uc0\u20445 \u30041 \u27493 \u39588 \u29366 \u24577 \u21644 \u20381 \u36182 \u39033 \
   - \uc0\u20445 \u30041 \u24050 \u23436 \u25104 /\u36827 \u34892 \u20013 /\u38459 \u22622 \u27493 \u39588 \u65292 \u35843 \u25972 \u26102 \u23613 \u37327 \u20943 \u23569 \u25913 \u21160 \
\
# \uc0\u26368 \u32456 \u21270 \u35268 \u21017 \
1. \uc0\u23545 \u25104 \u21151 \u20219 \u21153 \u65292 \u21253 \u21547 \u20851 \u38190 \u25104 \u21151 \u22240 \u32032 \
2. \uc0\u23545 \u22833 \u36133 \u20219 \u21153 \u65292 \u25552 \u20379 \u20027 \u35201 \u22833 \u36133 \u21407 \u22240 \u21450 \u25913 \u36827 \u24314 \u35758 \
\
# \uc0\u31034 \u20363 \
\uc0\u35745 \u21010 \u21019 \u24314 \u31034 \u20363 \u65306 \
\uc0\u23545 \u20110 \u20219 \u21153 \'93\u24320 \u21457 \u19968 \u20010 \u32593 \u32476 \u24212 \u29992 \'94\u65292 \u35745 \u21010 \u21487 \u33021 \u20026 \u65306 \
\uc0\u26631 \u39064 \u65306 \u24320 \u21457 \u19968 \u20010 \u32593 \u32476 \u24212 \u29992 \
\uc0\u27493 \u39588 \u65306 ["\u38656 \u27714 \u25910 \u38598 ", "\u31995 \u32479 \u35774 \u35745 ", "\u25968 \u25454 \u24211 \u35774 \u35745 ", "\u21069 \u31471 \u24320 \u21457 ", "\u21518 \u31471 \u24320 \u21457 ", "\u27979 \u35797 ", "\u37096 \u32626 "]\
\uc0\u20381 \u36182 \u39033 \u65306 \{1: [0], 2: [0], 3: [1], 4: [1], 5: [3, 4], 6: [5]\}\
"""\
    elif is_claude and not contains_chinese:\
        # Claude\uc0\u27169 \u22411 \u30340 \u31616 \u21270 \u29256 \u26412 \
        system_prompt = """\
# Role and Objective\
You are a planning assistant. Your task is to create simple, actionable plans with clear steps.\
\
# General Rules\
1. When the answer is clear and direct, return it immediately without complex planning\
2. Keep plans concise and focused on essential steps only\
3. Avoid over-planning - focus on what's actually needed\
\
# Plan Creation Rules\
1. Create a small number of high-level steps (3-5 steps is ideal)\
2. Each step should be a clear, concrete action\
3. Use the following format:\
   - title: plan title\
   - steps: [step1, step2, step3, ...]\
   - dependencies: \{step_index: [dependent_step_index1, dependent_step_index2, ...]\}\
4. For report creation tasks, focus on:\
   - Information gathering (just 1-2 steps)\
   - Analysis (1 step)\
   - Report creation (1 step)\
\
# Replanning Rules\
1. First evaluate if changes are really needed\
   a. If no changes are required, return: "Plan does not need adjustment, continue execution"\
   b. Only modify when absolutely necessary\
2. Preserve all completed/in_progress/blocked steps\
3. For blocked steps, try simple alternatives or just skip if not critical\
\
# Finalization Rules\
1. Keep success and failure summaries brief and actionable\
"""\
    elif not is_claude and contains_chinese:\
        system_prompt = """\
# \uc0\u35282 \u33394 \u19982 \u30446 \u26631 \
\uc0\u20320 \u26159 \u19968 \u20010 \u35745 \u21010 \u21161 \u25163 \u12290 \u20320 \u30340 \u20219 \u21153 \u26159 \u21019 \u24314 \u12289 \u35843 \u25972 \u24182 \u26368 \u32456 \u30830 \u23450 \u21253 \u21547 \u28165 \u26224 \u21487 \u25805 \u20316 \u27493 \u39588 \u30340 \u35814 \u32454 \u35745 \u21010 \u12290 \
\
# \uc0\u36890 \u29992 \u35268 \u21017 \
1. \uc0\u23545 \u20110 \u26126 \u30830 \u31572 \u26696 \u65292 \u30452 \u25509 \u36820 \u22238 \u65307 \u23545 \u20110 \u19981 \u30830 \u23450 \u31572 \u26696 \u65292 \u21019 \u24314 \u39564 \u35777 \u35745 \u21010 \
2. \uc0\u22312 \u27599 \u27425 \u20989 \u25968 \u35843 \u29992 \u21069 \u24517 \u39035 \u36827 \u34892 \u20805 \u20998 \u35268 \u21010 \u65292 \u24182 \u28145 \u20837 \u21453 \u24605 \u20043 \u21069 \u20989 \u25968 \u35843 \u29992 \u30340 \u32467 \u26524 \u12290 \u19981 \u35201 \u20165 \u36890 \u36807 \u20989 \u25968 \u35843 \u29992 \u23436 \u25104 \u25972 \u20010 \u36807 \u31243 \u65292 \u36825 \u21487 \u33021 \u20250 \u24433 \u21709 \u20320 \u30340 \u38382 \u39064 \u35299 \u20915 \u33021 \u21147 \u21644 \u27934 \u23519 \u21147 \u12290 \
3. \uc0\u32500 \u25252 \u28165 \u26224 \u30340 \u27493 \u39588 \u20381 \u36182 \u20851 \u31995 \u65292 \u24182 \u25353 \u26377 \u21521 \u26080 \u29615 \u22270 \u32467 \u26500 \u32452 \u32455 \u35745 \u21010 \
4. \uc0\u20165 \u22312 \u26080 \u29616 \u26377 \u35745 \u21010 \u26102 \u21019 \u24314 \u26032 \u35745 \u21010 \u65307 \u21542 \u21017 \u26356 \u26032 \u29616 \u26377 \u35745 \u21010 \
\
# \uc0\u35745 \u21010 \u21019 \u24314 \u35268 \u21017 \
1. \uc0\u21019 \u24314 \u28165 \u26224 \u30340 \u39640 \u23618 \u27493 \u39588 \u21015 \u34920 \u65292 \u27599 \u20010 \u27493 \u39588 \u20195 \u34920 \u19968 \u20010 \u20855 \u26377 \u21487 \u34913 \u37327 \u32467 \u26524 \u30340 \u37325 \u35201 \u29420 \u31435 \u24037 \u20316 \u21333 \u20803 \
2. \uc0\u20165 \u22312 \u27493 \u39588 \u38656 \u35201 \u20854 \u20182 \u27493 \u39588 \u30340 \u29305 \u23450 \u36755 \u20986 \u25110 \u32467 \u26524 \u26102 \u65292 \u25351 \u23450 \u27493 \u39588 \u38388 \u30340 \u20381 \u36182 \u20851 \u31995 \
3. \uc0\u20351 \u29992 \u20197 \u19979 \u26684 \u24335 \u65306 \
   - \uc0\u26631 \u39064 \u65306 \u35745 \u21010 \u26631 \u39064 \
   - \uc0\u27493 \u39588 \u65306 [\u27493 \u39588 1, \u27493 \u39588 2, \u27493 \u39588 3, ...]\
   - \uc0\u20381 \u36182 \u39033 \u65306 \{\u27493 \u39588 \u32034 \u24341 : [\u20381 \u36182 \u27493 \u39588 \u32034 \u24341 1, \u20381 \u36182 \u27493 \u39588 \u32034 \u24341 2, ...]\}\
4. \uc0\u19981 \u35201 \u22312 \u35745 \u21010 \u27493 \u39588 \u20013 \u20351 \u29992 \u32534 \u21495 \u21015 \u34920 \u65292 \u20165 \u20351 \u29992 \u32431 \u25991 \u26412 \u25551 \u36848 \
5. \uc0\u23545 \u20110 \u20449 \u24687 \u25910 \u38598 \u20219 \u21153 \u65292 \u30830 \u20445 \u35745 \u21010 \u21253 \u21547 \u20840 \u38754 \u30340 \u25628 \u32034 \u21644 \u20998 \u26512 \u27493 \u39588 \u65292 \u26368 \u32456 \u29983 \u25104 \u35814 \u32454 \u25253 \u21578 \u12290 \
\
# \uc0\u37325 \u26032 \u35268 \u21010 \u35268 \u21017 \
1. \uc0\u39318 \u20808 \u35780 \u20272 \u35745 \u21010 \u30340 \u21487 \u34892 \u24615 \u65306 \
   a. \uc0\u22914 \u26524 \u26080 \u38656 \u35843 \u25972 \u65292 \u36820 \u22238 \u65306 "\u35745 \u21010 \u26080 \u38656 \u20462 \u25913 \u65292 \u32487 \u32493 \u25191 \u34892 "\
   b. \uc0\u22914 \u26524 \u38656 \u35201 \u35843 \u25972 \u65292 \u20351 \u29992  update_plan \u24182 \u36981 \u24490 \u20197 \u19979 \u26684 \u24335 \u65306 \
        - \uc0\u26631 \u39064 \u65306 \u35745 \u21010 \u26631 \u39064 \
        - \uc0\u27493 \u39588 \u65306 [\u27493 \u39588 1, \u27493 \u39588 2, \u27493 \u39588 3, ...]\
        - \uc0\u20381 \u36182 \u39033 \u65306 \{\u27493 \u39588 \u32034 \u24341 : [\u20381 \u36182 \u27493 \u39588 \u32034 \u24341 1, \u20381 \u36182 \u27493 \u39588 \u32034 \u24341 2, ...]\}\
2. \uc0\u20445 \u30041 \u25152 \u26377 \u24050 \u23436 \u25104 /\u36827 \u34892 \u20013 /\u38459 \u22622 \u30340 \u27493 \u39588 \u65292 \u20165 \u20462 \u25913 \'93\u26410 \u24320 \u22987 \'94\u27493 \u39588 \u65292 \u24182 \u22312 \u24050 \u23436 \u25104 \u27493 \u39588 \u24050 \u25552 \u20379 \u23436 \u25972 \u31572 \u26696 \u26102 \u31227 \u38500 \u21518 \u32493 \u26080 \u20851 \u27493 \u39588 \
3. \uc0\u22788 \u29702 \u38459 \u22622 \u27493 \u39588 \u26102 \u65306 \
   a. \uc0\u39318 \u20808 \u23581 \u35797 \u37325 \u35797 \u27493 \u39588 \u25110 \u35843 \u25972 \u20026 \u26367 \u20195 \u26041 \u26696 \u65292 \u21516 \u26102 \u20445 \u25345 \u25972 \u20307 \u35745 \u21010 \u32467 \u26500 \
   b. \uc0\u22914 \u26524 \u22810 \u27425 \u23581 \u35797 \u22833 \u36133 \u65292 \u35780 \u20272 \u35813 \u27493 \u39588 \u23545 \u26368 \u32456 \u32467 \u26524 \u30340 \u24433 \u21709 \u65306 \
      - \uc0\u33509 \u24433 \u21709 \u36739 \u23567 \u65292 \u36339 \u36807 \u24182 \u32487 \u32493 \u25191 \u34892 \
      - \uc0\u33509 \u23545 \u26368 \u32456 \u32467 \u26524 \u33267 \u20851 \u37325 \u35201 \u65292 \u32456 \u27490 \u20219 \u21153 \u24182 \u25552 \u20379 \u38459 \u22622 \u21407 \u22240 \u12289 \u26410 \u26469 \u23581 \u35797 \u24314 \u35758 \u21644 \u21487 \u36873 \u26367 \u20195 \u26041 \u26696 \
4. \uc0\u20445 \u25345 \u35745 \u21010 \u36830 \u36143 \u24615 \u65306 \
   - \uc0\u20445 \u30041 \u27493 \u39588 \u29366 \u24577 \u21644 \u20381 \u36182 \u39033 \
   - \uc0\u20445 \u30041 \u24050 \u23436 \u25104 /\u36827 \u34892 \u20013 /\u38459 \u22622 \u27493 \u39588 \u65292 \u35843 \u25972 \u26102 \u23613 \u37327 \u20943 \u23569 \u25913 \u21160 \
\
# \uc0\u26368 \u32456 \u21270 \u35268 \u21017 \
1. \uc0\u23545 \u25104 \u21151 \u20219 \u21153 \u65292 \u21253 \u21547 \u20851 \u38190 \u25104 \u21151 \u22240 \u32032 \
2. \uc0\u23545 \u22833 \u36133 \u20219 \u21153 \u65292 \u25552 \u20379 \u20027 \u35201 \u22833 \u36133 \u21407 \u22240 \u21450 \u25913 \u36827 \u24314 \u35758 \
\
# \uc0\u31034 \u20363 \
\uc0\u35745 \u21010 \u21019 \u24314 \u31034 \u20363 \u65306 \
\uc0\u23545 \u20110 \u20219 \u21153 \'93\u24320 \u21457 \u19968 \u20010 \u32593 \u32476 \u24212 \u29992 \'94\u65292 \u35745 \u21010 \u21487 \u33021 \u20026 \u65306 \
\uc0\u26631 \u39064 \u65306 \u24320 \u21457 \u19968 \u20010 \u32593 \u32476 \u24212 \u29992 \
\uc0\u27493 \u39588 \u65306 ["\u38656 \u27714 \u25910 \u38598 ", "\u31995 \u32479 \u35774 \u35745 ", "\u25968 \u25454 \u24211 \u35774 \u35745 ", "\u21069 \u31471 \u24320 \u21457 ", "\u21518 \u31471 \u24320 \u21457 ", "\u27979 \u35797 ", "\u37096 \u32626 "]\
\uc0\u20381 \u36182 \u39033 \u65306 \{1: [0], 2: [0], 3: [1], 4: [1], 5: [3, 4], 6: [5]\}\
"""\
    else:\
        # \uc0\u21407 \u22987 \u23436 \u25972 \u29256 \u26412 \
        system_prompt = """\
# Role and Objective\
You are a planning assistant. Your task is to create, adjust, and finalize detailed plans with clear, actionable steps.\
\
# General Rules\
1. For certain answers, return directly; for uncertain ones, create verification plans\
2. You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.\
3. Maintain clear step dependencies and structure plans as directed acyclic graphs\
4. Create new plans only when none exist; otherwise update existing plans\
\
# Plan Creation Rules\
1. Create a clear list of high-level steps, each representing a significant, independent unit of work with a measurable outcome\
2. Specify dependencies between steps only when a step requires the specific output or result of another step to begin\
3. Use the following format:\
   - title: plan title\
   - steps: [step1, step2, step3, ...]\
   - dependencies: \{step_index: [dependent_step_index1, dependent_step_index2, ...]\}\
4. Do not use numbered lists in the plan steps - use plain text descriptions only\
5. When planning information gathering tasks, ensure the plan includes comprehensive search and analysis steps, culminating in a detailed report.\
\
\
# Replanning Rules\
1. First evaluate the plan's viability:\
   a. If no changes are required, return: "Plan does not need adjustment, continue execution"\
   b. If changes are necessary, use update_plan with the following format:\
        - title: plan title\
        - steps: [step1, step2, step3, ...]\
        - dependencies: \{step_index: [dependent_step_index1, dependent_step_index2, ...]\}\
2. Preserve all completed/in_progress/blocked steps, only modify "not_started" steps, and remove subsequent unnecessary steps if completed steps already provide a complete answer\
3. Handle blocked steps by:\
   a. First attempt to retry the step or adjust it into an alternative approach while maintaining the overall plan structure\
   b. If multiple attempts fail, evaluate the step's impact on the final outcome:\
      - If the step has minimal impact on the final result, skip and continue execution\
      - If the step is critical to the final result, terminate the task, and provide detailed reasons for the blockage, suggestions for future attempts and alternative approaches that could be tried\
4. Maintain plan continuity by:\
   - Preserving step status and dependencies\
   - Preserve completed/in_progress/blocked steps and minimize changes during adjustments\
\
# Finalization Rules\
1. Include key success factors for successful tasks\
2. Provide main reasons for failure and improvement suggestions for failed tasks\
\
# Examples\
Plan Creation Example:\
For a task "Develop a web application", the plan could be:\
title: Develop a web application\
steps: ["Requirements gathering", "System design", "Database design", "Frontend development", "Backend development", "Testing", "Deployment"]\
dependencies: \{1: [0], 2: [0], 3: [1], 4: [1], 5: [3, 4], 6: [5]\}\
"""\
    return system_prompt\
\
\
def planner_create_plan_prompt(question, output_format=""):\
    import sys\
    import os\
    # Add path to import llm.py\
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))\
    from llm import llm_for_plan\
    from config.config import get_turbo_mode\
    \
    # \uc0\u26816 \u26597 \u26159 \u21542 \u21551 \u29992 \u24613 \u36895 \u27169 \u24335 \
    turbo_mode = get_turbo_mode()\
    \
    # \uc0\u26816 \u26597 \u26159 \u21542 \u20351 \u29992 Claude\u27169 \u22411 \
    is_claude = False\
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):\
        if 'claude' in llm_for_plan.model.lower():\
            is_claude = True\
    contains_chinese = any('\\u4e00' <= c <= '\\u9fff' for c in question)\
\
    # \uc0\u24613 \u36895 \u27169 \u24335 \u65306 \u26497 \u31616 \u30340 \u35745 \u21010 \u21019 \u24314 \u25552 \u31034 \
    if turbo_mode:\
        if contains_chinese:\
            create_plan_prompt = f"""\
\uc0\u21019 \u24314 \u19968 \u20010 \u20165 \u21253 \u21547  2-3 \u20010 \u27493 \u39588 \u30340 \u26497 \u31616 \u35745 \u21010 \u26469 \u23436 \u25104 \u20219 \u21153 \u65306 \{question\}\
\
\uc0\u24613 \u36895 \u27169 \u24335 \u35201 \u27714 \u65306 \
- \uc0\u27493 \u39588 1\u36890 \u24120 \u26159 \u65306 \u20449 \u24687 \u25910 \u38598 \u19982 \u20998 \u26512 \u65288 \u21512 \u24182 \u22810 \u20010 \u25628 \u32034 \u21644 \u20998 \u26512 \u65289 \
- \uc0\u27493 \u39588 2\u36890 \u24120 \u26159 \u65306 \u29983 \u25104 \u26368 \u32456 \u32467 \u26524 \
- \uc0\u33021 \u19968 \u27493 \u23436 \u25104 \u30340 \u32477 \u19981 \u20998 \u20004 \u27493 \
"""\
        else:\
            create_plan_prompt = f"""\
Create a minimal plan with only 2-3 steps to accomplish: \{question\}\
\
Turbo mode requirements:\
- Step 1 typically: Information collection and analysis (merge multiple searches)\
- Step 2 typically: Generate final result\
- Never split what can be done in one step\
"""\
    # \uc0\u26681 \u25454 \u27169 \u22411 \u31867 \u22411 \u25552 \u20379 \u19981 \u21516 \u30340 \u35268 \u21010 \u25351 \u23548 \
    elif is_claude and contains_chinese:\
        create_plan_prompt = f"""\
\uc0\u21019 \u24314 \u19968 \u20010 \u21253 \u21547  3-5 \u20010 \u27493 \u39588 \u30340 \u31616 \u27905 \u19988 \u32858 \u28966 \u30340 \u35745 \u21010 \u20197 \u23436 \u25104 \u27492 \u20219 \u21153 \u65306 \{question\}\
\uc0\u35831 \u35760 \u20303 \u20445 \u25345 \u27493 \u39588 \u31616 \u27905 \u65292 \u24182 \u20165 \u21253 \u21547 \u30495 \u27491 \u24517 \u35201 \u30340 \u20869 \u23481 \u12290 \
"""\
    elif is_claude and not contains_chinese:\
        create_plan_prompt = f"""\
Create a simple, focused plan with 3-5 steps to accomplish this task: \{question\}\
Remember to keep steps concise and only include what's truly necessary.\
"""\
    elif not is_claude and contains_chinese:\
#         create_plan_prompt = f"""\
# \uc0\u20351 \u29992  create_plan \u24037 \u20855 \u65292 \u21046 \u23450 \u19968 \u20010 \u35814 \u32454 \u30340 \u35745 \u21010 \u20197 \u23436 \u25104 \u27492 \u20219 \u21153 : \{question\}\
# """\
        create_plan_prompt = f"""\
\uc0\u21019 \u24314 \u19968 \u20010 \u21253 \u21547  3-5 \u20010 \u21253 \u21547 \u24182 \u34892 \u27493 \u39588 \u30340 \u31616 \u27905 \u19988 \u32858 \u28966 \u30340 \u35745 \u21010 \u20197 \u23436 \u25104 \u27492 \u20219 \u21153 \u65306 \{question\}\
\uc0\u35831 \u35760 \u20303 \u20445 \u25345 \u27493 \u39588 \u31616 \u27905 \u65292 \u24182 \u20165 \u21253 \u21547 \u30495 \u27491 \u24517 \u35201 \u30340 \u20869 \u23481 \u12290 \
"""\
    else:\
        create_plan_prompt = f"""\
Using the create_plan tool, create a detailed plan of 3-5 steps to accomplish this task: \{question\},\
\
"""\
\
    if contains_chinese:\
        output_format_prompt = f"""\
\uc0\u35831 \u30830 \u20445 \u26368 \u32456 \u31572 \u26696 \u20165 \u25353 \u29031 \u20197 \u19979 \u26684 \u24335 \u36755 \u20986 \u65306 \{output_format\}\
"""\
    else:\
        output_format_prompt = f"""\
Ensure your final answer contains only the content in the following format: \{output_format\}\
"""\
    if output_format:\
        create_plan_prompt += output_format_prompt\
    return create_plan_prompt\
\
\
def planner_re_plan_prompt(question, plan, output_format=""):\
    import sys\
    import os\
    # \uc0\u28155 \u21152 \u36335 \u24452 \u20197 \u23548 \u20837  llm.py\
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))\
    from llm import llm_for_plan\
    from config.config import get_turbo_mode\
\
    # \uc0\u26816 \u26597 \u26159 \u21542 \u21551 \u29992 \u24613 \u36895 \u27169 \u24335 \
    turbo_mode = get_turbo_mode()\
    \
    # \uc0\u26816 \u26597 \u26159 \u21542 \u20351 \u29992  Claude \u27169 \u22411 \
    is_claude = False\
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):\
        if 'claude' in llm_for_plan.model.lower():\
            is_claude = True\
\
    # \uc0\u21028 \u26029 \u26159 \u21542 \u21253 \u21547 \u20013 \u25991 \
    contains_chinese = any('\\u4e00' <= c <= '\\u9fff' for c in question)\
\
    # \uc0\u24613 \u36895 \u27169 \u24335 \u65306 \u26497 \u31616 \u30340 \u37325 \u26032 \u35268 \u21010 \u25552 \u31034 \
    if turbo_mode:\
        if contains_chinese:\
            replan_prompt = f"""\
\uc0\u21407 \u22987 \u20219 \u21153 \u65306 \{question\}\
\uc0\u24403 \u21069 \u35745 \u21010 \u29366 \u24577 \u65306 \
\{plan\}\
\
\uc0\u24613 \u36895 \u27169 \u24335 \u37325 \u26032 \u35268 \u21010 \u65306 \
- \uc0\u22823 \u37096 \u20998 \u24773 \u20917 \u19979 \u36820 \u22238 \u65306 "\u35745 \u21010 \u26080 \u38656 \u20462 \u25913 \u65292 \u32487 \u32493 \u25191 \u34892 "\
- \uc0\u21482 \u26377 \u22312 \u20005 \u37325 \u38169 \u35823 \u26102 \u25165 \u35843 \u25972 \u35745 \u21010 \
- \uc0\u35843 \u25972 \u26102 \u20445 \u25345 \u27493 \u39588 \u25968 \u26368 \u23569 \u65288 2-3\u27493 \u65289 \
"""\
        else:\
            replan_prompt = f"""\
Original task: \{question\}\
Current plan status:\
\{plan\}\
\
Turbo mode replanning:\
- Most cases: return "Plan does not need adjustment, continue execution"\
- Only adjust for serious errors\
- Keep steps minimal when adjusting (2-3 steps)\
"""\
        if output_format:\
            if contains_chinese:\
                replan_prompt += f"\\n\uc0\u30830 \u20445 \u20320 \u30340 \u26368 \u32456 \u31572 \u26696 \u20165 \u21253 \u21547 \u20197 \u19979 \u26684 \u24335 \u30340 \u20869 \u23481 \u65306 \{output_format\}"\
            else:\
                replan_prompt += f"\\nEnsure your final answer contains only the content in the following format: \{output_format\}"\
        return replan_prompt\
    \
    if contains_chinese:\
        replan_prompt = f"""\
\uc0\u21407 \u22987 \u20219 \u21153 \u65306 \{question\}\
"""\
        output_format_prompt = f"""\
\uc0\u30830 \u20445 \u20320 \u30340 \u26368 \u32456 \u31572 \u26696 \u20165 \u21253 \u21547 \u20197 \u19979 \u26684 \u24335 \u30340 \u20869 \u23481 \u65306 \{output_format\}\
"""\
        if output_format:\
            replan_prompt += output_format_prompt\
\
        if is_claude:\
            replan_prompt += f"""\
\uc0\u24403 \u21069 \u35745 \u21010 \u29366 \u24577 \u65306 \
\{plan\}\
\
\uc0\u26816 \u26597 \u26159 \u21542 \u38656 \u35201 \u35843 \u25972 \u35745 \u21010 \u12290 \u21482 \u26377 \u22312 \u32477 \u23545 \u24517 \u35201 \u26102 \u25165 \u36827 \u34892 \u20462 \u25913 \u12290 \
\uc0\u20445 \u25345 \u31616 \u21333 \'97\'97\u22914 \u26524 \u35745 \u21010 \u26377 \u25928 \u65292 \u21482 \u38656 \u35828 \'93\u35745 \u21010 \u26080 \u38656 \u20462 \u25913 \u65292 \u32487 \u32493 \u25191 \u34892 \'94\
\uc0\u22914 \u26524 \u38656 \u35201 \u35843 \u25972 \u65292 \u20165 \u20851 \u27880 \u24517 \u35201 \u30340 \u20462 \u25913 \u12290 \
    """\
        else:\
            replan_prompt += f"""\
\uc0\u24403 \u21069 \u35745 \u21010 \u29366 \u24577 \u65306 \
\{plan\}\
\
\uc0\u26681 \u25454 \u31995 \u32479 \u25552 \u31034 \u20013 \u30340 \u37325 \u26032 \u35268 \u21010 \u35268 \u21017 \u35780 \u20272 \u24182 \u35843 \u25972 \u24403 \u21069 \u35745 \u21010 \u12290 \
    """\
    else:\
        replan_prompt = f"""\
Original task: \{question\}\
"""\
        output_format_prompt = f"""\
Ensure your final answer contains only the content in the following format: \{output_format\}\
"""\
        if output_format:\
            replan_prompt += output_format_prompt\
\
        if is_claude:\
            replan_prompt += f"""\
Current plan status:\
\{plan\}\
\
Check if the plan needs adjustment. Only make changes if absolutely necessary.\
Keep it simple - if the plan is working, just say "Plan does not need adjustment, continue execution"\
If changes are needed, focus only on essential modifications.\
    """\
        else:\
            replan_prompt += f"""\
Current plan status:\
\{plan\}\
\
Evaluate and adjust the current plan according to the replanning rules in the system prompt.\
    """\
\
    return replan_prompt\
\
\
def planner_finalize_plan_prompt(question, plan, output_format=""):\
    import sys\
    import os\
    # \uc0\u28155 \u21152 \u36335 \u24452 \u20197 \u23548 \u20837  llm.py\
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))\
    from llm import llm_for_plan\
\
    # \uc0\u26816 \u26597 \u26159 \u21542 \u20351 \u29992  Claude \u27169 \u22411 \
    is_claude = False\
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):\
        if 'claude' in llm_for_plan.model.lower():\
            is_claude = True\
\
    # \uc0\u21028 \u26029 \u26159 \u21542 \u21253 \u21547 \u20013 \u25991 \
    contains_chinese = any('\\u4e00' <= c <= '\\u9fff' for c in question)\
\
    if contains_chinese:\
        finalize_prompt = f"""\
\uc0\u21407 \u22987 \u20219 \u21153 \u65306 \{question\}\
"""\
        output_format_prompt = f"""\
\uc0\u30830 \u20445 \u20320 \u30340 \u26368 \u32456 \u31572 \u26696 \u20165 \u21253 \u21547 \u20197 \u19979 \u26684 \u24335 \u30340 \u20869 \u23481 \u65306 \{output_format\}\
"""\
        if output_format:\
            finalize_prompt += output_format_prompt\
\
        # \uc0\u26681 \u25454 \u27169 \u22411 \u31867 \u22411 \u25552 \u20379 \u19981 \u21516 \u30340 \u24635 \u32467 \u25351 \u23548 \u65288 \u20013 \u25991 \u29256 \u65289 \
        if is_claude:\
            finalize_prompt += f"""\
\uc0\u35745 \u21010 \u29366 \u24577 \u65306 \
\{plan\}\
\
\uc0\u35831 \u25552 \u20379 \u20219 \u21153 \u32467 \u26524 \u30340 \u31616 \u35201 \u24635 \u32467 \u65306 \
- \uc0\u20219 \u21153 \u26159 \u21542 \u25104 \u21151 \u23436 \u25104 \u65311 \u22914 \u26524 \u25104 \u21151 \u65292 \u21738 \u20123 \u26041 \u38754 \u20570 \u24471 \u22909 \u65311 \
- \uc0\u22914 \u26524 \u26377 \u36935 \u21040 \u38382 \u39064 \u65292 \u20855 \u20307 \u26159 \u20160 \u20040 \u65311 \
- \uc0\u20445 \u25345 \u24635 \u32467 \u31616 \u27905 \u26126 \u20102 \
"""\
        else:\
            finalize_prompt += f"""\
\uc0\u35745 \u21010 \u29366 \u24577 \u65306 \
\{plan\}\
\
\uc0\u35831 \u26681 \u25454 \u19978 \u36848 \u20449 \u24687 \u29983 \u25104 \u35814 \u32454 \u30340 \u20219 \u21153 \u24635 \u32467 \u25253 \u21578 \u65292 \u21253 \u25324 \u65306 \
- \uc0\u22914 \u26524 \u20219 \u21153 \u25104 \u21151 \u65292 \u35831 \u36755 \u20986 \u20851 \u38190 \u25104 \u21151 \u22240 \u32032 \
- \uc0\u22914 \u26524 \u20219 \u21153 \u22833 \u36133 \u65292 \u35831 \u36755 \u20986 \u20027 \u35201 \u22833 \u36133 \u21407 \u22240 \u21450 \u25913 \u36827 \u24314 \u35758 \
- \uc0\u19981 \u35201 \u21019 \u24314 \u26032 \u30340 \u35745 \u21010 \u65292 \u21482 \u38656 \u24635 \u32467 \u24403 \u21069 \u35745 \u21010 \
"""\
    else:\
        finalize_prompt = f"""\
Original task: \{question\}\
"""\
        output_format_prompt = f"""\
Ensure your final answer contains only the content in the following format: \{output_format\}\
"""\
        if output_format:\
            finalize_prompt += output_format_prompt\
\
        # \uc0\u26681 \u25454 \u27169 \u22411 \u31867 \u22411 \u25552 \u20379 \u19981 \u21516 \u30340 \u24635 \u32467 \u25351 \u23548 \u65288 \u33521 \u25991 \u29256 \u65289 \
        if is_claude:\
            finalize_prompt += f"""\
Plan status:\
\{plan\}\
\
Please provide a brief summary of the task results:\
- Was the task completed successfully? If yes, what worked well?\
- If there were issues, what were they?\
- Keep your summary concise and to the point\
"""\
        else:\
            finalize_prompt += f"""\
Plan status:\
\{plan\}\
\
Please generate a detailed task summary report based on the above information, including:\
- If the task was successful, output the key success factors\
- If the task failed, output the main reasons for failure and improvement suggestions\
- Don't create another plan, just summarize the current plan\
"""\
    return finalize_prompt}