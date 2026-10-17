"""Guion del documental 'The Gulf of Tonkin' (Stunning Revelations, 16:9, ~10 min). Mismo formato que nwdoc/script.py.
Datos: Wikipedia (Gulf of Tonkin incident, Southeast Asia Resolution), NSA/Hanyok 2001 (desclasificado 30-11-2005),
votos del Congreso (House 416-0, Senate 88-2), Stockdale 'Love and War' (1984), McNamara 'The Fog of War' (2003)."""
NW, DOC = ".", "dl"
WV = f"{DOC}/gov.ntis.ava08194vnb1.mpeg"           # Why Vietnam? (DoD, 1965)
PC20, PC06 = f"{DOC}/111-lc-48220.mp4", f"{DOC}/111-lc-48206.mp4"   # conferencias de prensa, agosto 1964
MAD = f"{DOC}/428-npc-1612.mp4"                    # USS Maddox, 1954 (US Navy)
SH, MA, VA = f"{DOC}/1965-02-08_Showdown_in_Vietnam.mpeg", f"{DOC}/1965-04-29_Marines_In_Action.mpeg", f"{DOC}/1965-12-09_Vietnam_Action.mpeg"

SCRIPT = [
    ("August 4, 1964. Just before midnight, President Lyndon Johnson goes on national television.",
     [("v", WV, 1062.0, 1072.0)]),
    ("American destroyers, he says, have been attacked for a second time by North Vietnamese boats in the Gulf of Tonkin. "
     "American planes are already in the air.",
     [("v", WV, 1072.0, 1088.0), ("v", MAD, 330.0, 345.0)]),
    ("Three days later, Congress gives him the power to use armed force in Southeast Asia. That decision will lead to a war "
     "that kills more than fifty-eight thousand Americans, and Vietnamese in the millions.",
     [("v", WV, 1572.0, 1600.0), ("v", WV, 1645.0, 1690.0)]),
    ("There was only one problem. The second attack never happened.", [("neg",), ("v", MAD, 100.0, 132.0)]),
    ("card", "THE GULF OF TONKIN"),

    ("card", "1 · A SECRET WAR"),
    ("By 1964, the United States had more than sixteen thousand military advisers in South Vietnam. Publicly, America was "
     "only helping an ally. In secret, it was doing more.",
     [("v", WV, 380.0, 390.0), ("v", WV, 845.0, 870.0)]),
    ("Since 1961, South Vietnamese commandos, trained and directed by the Americans, had been raiding the coast of North "
     "Vietnam. The program had a code name: Operation Plan 34A. In 1964, the Pentagon took it over.",
     [("v", WV, 985.0, 1010.0), ("v", WV, 1100.0, 1118.0)]),
    ("At the same time, American destroyers sailed along the same coast on spy missions called DESOTO patrols, packed with "
     "equipment to listen to North Vietnamese radio.",
     [("v", MAD, 10.0, 36.0), ("v", MAD, 350.0, 386.0)]),
    ("Their job was to map the radar sites and coastal defenses of North Vietnam. The same defenses the commandos were "
     "attacking.",
     [("doc", "h05", "with critical intelligence regarding North Vietnam’s ability to resist its projected commando operations"), ("v", MAD, 386.0, 398.0)]),
    ("On the night of July 30, commandos raided a radar station on the island of Hon Me. Two days later, the destroyer USS "
     "Maddox was patrolling nearby.",
     [("v", PC20, 588.0, 600.0), ("v", MAD, 300.0, 330.0)]),

    ("card", "2 · AUGUST 2"),
    ("On the afternoon of August 2, three North Vietnamese torpedo boats raced toward the Maddox. The destroyer fired "
     "three warning shots. Then the boats attacked.",
     [("v", PC20, 600.0, 640.0), ("v", MAD, 360.0, 386.0)]),
    ("Four F-8 Crusader jets from the carrier USS Ticonderoga joined the fight. The boats were badly damaged. "
     "Four North Vietnamese sailors were killed.",
     [("v", SH, 108.0, 136.0), ("v", MAD, 200.0, 226.0)]),
    ("The Maddox was hit by a single machine gun bullet. No American was hurt.", [("v", MAD, 330.0, 345.0)]),
    ("That clash was real. Washington chose not to retaliate. Instead, Johnson ordered the patrol to continue, and sent a "
     "second destroyer, the USS Turner Joy, to join it.",
     [("v", WV, 5.0, 25.0), ("v", MAD, 428.0, 440.0)]),

    ("card", "3 · THE NIGHT OF AUGUST 4"),
    ("Two nights later, the weather turned. Rough weather, heavy seas, a dark night. On the radar screens, the crews began to see "
     "contacts that seemed to be closing in.",
     [("v", MAD, 78.0, 100.0), ("v", MAD, 100.0, 140.0)]),
    ("For about two hours, the two destroyers fired at targets in the dark. The sonar operators reported more than twenty "
     "torpedoes in the water.",
     [("v", MAD, 360.0, 386.0), ("v", PC06, 390.0, 430.0)]),
    ("Above them flew Commander James Stockdale, a Navy squadron commander. He searched the water for the attacking "
     "boats. He found nothing.",
     [("v", MAD, 490.0, 520.0), ("v", WV, 1762.0, 1790.0)]),
    ("Years later, he wrote that the destroyers had been shooting at phantom targets. No wreckage was ever found. "
     "No bodies.",
     [("neg",), ("v", MAD, 100.0, 140.0)]),
    ("Within hours, the task force commander, Captain John Herrick, sent an urgent cable. Review of action makes many "
     "reported contacts and torpedoes fired appear doubtful.",
     [("doc", "h01", "he was doubtful of many aspects of the")]),
    ("He blamed freak weather and overeager sonar operators. And he asked for one thing: a complete evaluation before any "
     "further action taken.",
     [("doc", "h24", "makes many reported contacts and torpedoes fired appear doubtful because of freak weather, over-eager sonar")]),

    ("card", "4 · THE DECISION"),
    ("In Washington, the evaluation did not wait. Within hours of the first reports, retaliation had already been decided. "
     "It was called Operation Pierce Arrow.",
     [("v", PC06, 300.0, 330.0), ("v", PC06, 400.0, 460.0)]),
    ("Just before midnight, Johnson went on television. Repeated acts of violence against the armed forces of the United "
     "States, he said, must be met not only with alert defense, but with positive reply.",
     [("v", WV, 1062.0, 1088.0)]),
    ("As he spoke, aircraft were taking off. The next day, they bombed four torpedo boat bases and an oil storage depot "
     "at Vinh.",
     [("v", SH, 110.0, 160.0), ("v", VA, 6.0, 30.0)]),
    ("Secretary of Defense Robert McNamara stood before the press with a map of the Gulf, and walked reporters through "
     "the attack, step by step.",
     [("v", PC06, 380.0, 420.0), ("v", PC06, 470.0, 530.0), ("v", PC06, 300.0, 330.0)]),
    ("Congress was told the attacks were unprovoked, and that the Navy had nothing to do with the secret raids "
     "along the coast.",
     [("v", PC20, 100.0, 130.0), ("v", WV, 1125.0, 1140.0)]),

    ("It was also an election year. In three months, Johnson would face the Republican Barry Goldwater, who was demanding "
     "a tougher line in Vietnam. Now the President had answered with force.",
     [("v", WV, 1395.0, 1430.0), ("v", SH, 254.0, 280.0)]),
    ("card", "5 · THE BLANK CHECK"),
    ("On August 7, Congress voted on a resolution allowing the President to take all necessary steps, including the use "
     "of armed force. It was not a declaration of war. It did not need to be.",
     [("txt", "H.J. RES. 1145", "all necessary steps, including the use of armed force"), ("v", WV, 1395.0, 1420.0)]),
    ("The House passed it four hundred sixteen to zero. In the Senate, the vote was eighty-eight to two.",
     [("txt", "HOUSE 416 – 0", "SENATE 88 – 2")]),
    ("Only two senators said no: Wayne Morse of Oregon and Ernest Gruening of Alaska. Morse called the American actions "
     "acts of war rather than acts of defense. Both men lost their seats in 1968.",
     [("v", SH, 238.0, 252.0), ("v", WV, 1420.0, 1460.0)]),
    ("Johnson signed the resolution on August 10. Later, he was quoted as saying privately: for all I know, our Navy was "
     "shooting at whales out there.",
     [("v", WV, 1395.0, 1420.0), ("v", MAD, 100.0, 130.0)]),
    ("In March 1965, the first American combat troops, thirty-five hundred Marines, came ashore at Da Nang. By 1968, "
     "more than half a million Americans were in Vietnam.",
     [("v", WV, 1572.0, 1610.0), ("v", MA, 50.0, 70.0), ("v", MA, 82.0, 100.0)]),
    ("The war lasted another decade. Its legal foundation was a night in the Gulf of Tonkin when, as far as anyone could "
     "prove, nothing happened.",
     [("v", VA, 34.0, 60.0), ("v", WV, 1645.0, 1690.0), ("v", MAD, 100.0, 132.0)]),

    ("In 1970, as protests spread across the country, the Senate voted to repeal the Tonkin resolution. By then, the war "
     "had already spread into Cambodia, and it would go on for five more years.",
     [("v", VA, 60.0, 90.0), ("v", WV, 1765.0, 1790.0)]),
    ("card", "6 · WHAT THE NSA KNEW"),
    ("In 1995, McNamara traveled to Hanoi and asked the North Vietnamese general Vo Nguyen Giap what had happened on "
     "August 4. Giap's answer: absolutely nothing.",
     [("v", WV, 1125.0, 1140.0), ("v", PC20, 130.0, 160.0)]),
    ("Years later, in the documentary The Fog of War, McNamara admitted it. There had been no attack that night.",
     [("v", PC06, 300.0, 330.0)]),
    ("Recordings of the White House phone calls, released in 2001, show McNamara voicing those doubts to the President "
     "within days of the attack.",
     [("v", PC20, 160.0, 200.0), ("v", WV, 1440.0, 1460.0)]),
    ("But the most important evidence was inside the National Security Agency. In 2001, an NSA historian named Robert "
     "Hanyok published a study in the agency's classified journal.",
     [("doc", "h01", "Skunks, Bogies, Silent Hounds, and the Flying Fish")]),
    ("Its title: Skunks, Bogies, Silent Hounds, and the Flying Fish. Hanyok had gone back to the original intercepts of "
     "North Vietnamese radio traffic.",
     [("doc", "h01", "The Gulf of Tonkin Mystery, 2-4 August 1964")]),
    ("His first finding was simple: no attack happened that night. Hanoi's navy, he wrote, was engaged in nothing that "
     "night but the salvage of two of the boats damaged on August 2.",
     [("doc", "h03", "no attack happened that night"), ("doc", "h03", "engaged in nothing that night but the salvage")]),
    ("His second finding was worse. The overwhelming body of reports, he wrote, would have told the story that no attack "
     "had happened. Instead, the summaries sent to Washington were deliberately skewed to support the notion that there had "
     "been an attack.",
     [("doc", "h49", "overwhelming body of reports, if used, would have told the story that no attack had happened"),
      ("doc", "h49", "deliberately skewed to support the notion that there had been an attack")]),
    ("Hanyok found no evidence that the White House ordered it. But the study stayed classified for four more years. The "
     "NSA released it on November 30, 2005.",
     [("doc", "h01", "Skunks, Bogies, Silent Hounds, and the Flying Fish"), ("stamp", "pg/h01", "DECLASSIFIED")]),

    ("card", "7 · WHAT IT MEANS"),
    ("Two years before Tonkin, the Joint Chiefs had proposed inventing an attack to justify a war with Cuba. That plan, "
     "Operation Northwoods, was rejected.",
     [("pgk", "../northwoods/nw/pg", "ship"), ("v", WV, 5.0, 25.0)]),
    ("The Gulf of Tonkin was different. No one has shown that it was planned. But when the evidence was uncertain, the "
     "uncertainty was left out.",
     [("v", PC06, 400.0, 460.0), ("doc", "h01", "he was doubtful of many aspects of the")]),
    ("A captain asked for a complete evaluation before any further action. The action came first. The evaluation came "
     "forty years later.",
     [("doc", "h24", "makes many reported contacts and torpedoes fired appear doubtful because of freak weather, over-eager sonar"), ("stamp", "pg/h03", "TOP SECRET")]),
    ("What else is still in the files? If you want more declassified stories like this one, subscribe to Stunning "
     "Revelations.",
     [("v", MAD, 100.0, 132.0)]),
]
