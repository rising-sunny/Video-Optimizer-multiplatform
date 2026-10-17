"""Guion del documental 'Operation Northwoods' (Stunning Revelations, 16:9, ~9-10 min).
Cada linea: ("card", capitulo) o (texto narrado, [visuales]). Visuales:
  ("v", archivo, desde, hasta)  video de archivo      ("ph", foto)  foto (LoC)
  ("pg", pagina, [(y0,y1)...]) pagina del memo con las lineas (fraccion de alto) resaltadas
  ("pgk", clave)  pagina ya resaltada del Short (nw/pg)   ("stamp", pagina, texto)  pagina con sello
  ("neg",) impacto en negativo antes del siguiente visual
Datos: memo JCS 13-3-1962 (leido en las paginas escaneadas) y Wikipedia (Northwoods, Bay of Pigs, Mongoose)."""
NW, DOC = "../nw", "dl"
CASTRO, SCARE, BREAK, INVADED, GLENN = (f"{DOC}/1959-01-05_Castro_Triumphs.mpeg", f"{DOC}/1960-10-31_Invasion_Scare.mpeg",
                                         f"{DOC}/1961-01-05_US_Breaks_Relations_With_Cuba.mpeg", f"{DOC}/1961-04-19_Cuba_Invaded.mpeg",
                                         f"{DOC}/1962-02-22_Space_Triumph.mpeg")
RT, CC, JET, MIA = f"{NW}/vid/red_threat.mpeg", f"{NW}/vid/cuban_crisis.mpeg", f"{NW}/vid/jet_national.mpeg", f"{NW}/vid/miami_1955.mp4"
LOC = f"{NW}/loc"

SCRIPT = [
    ("March 13, 1962. In the Pentagon, the highest-ranking officer in the United States military signs a memo stamped Top Secret.",
     [("stamp", "p00", "TOP SECRET"), ("pgk", "signature")]),
    ("Its subject: justification for US military intervention in Cuba. Inside are plans to blow up an American ship, to stage a terror "
     "campaign in American cities, and to fake the shootdown of a passenger plane full of college students.",
     [("pgk", "subject"), ("pgk", "ship"), ("pgk", "terror"), ("pgk", "students")]),
    ("All of it would be blamed on Cuba.", [("neg",), ("v", CC, 113.0, 123.0)]),
    ("The plan had a code name: Northwoods. It was real. It was signed. And for thirty-five years, almost no one knew it existed.",
     [("pgk", "northwoods"), ("ph", f"{LOC}/jfk_jcs.tif"), ("pgk", "topsecret")]),
    ("card", "OPERATION NORTHWOODS"),

    ("card", "1 · THE ISLAND NINETY MILES AWAY"),
    ("In January 1959, Fidel Castro's rebels rolled into Havana. The crowds cheered. Washington watched.",
     [("v", CASTRO, 8.0, 14.0), ("v", CASTRO, 92.0, 108.0), ("v", CASTRO, 130.0, 139.0)]),
    ("Within two years, Castro had nationalized American businesses and moved closer to the Soviet Union. In January 1961, the United "
     "States broke diplomatic relations with Cuba.",
     [("v", SCARE, 19.0, 36.0), ("v", SCARE, 9.0, 16.0), ("v", BREAK, 30.0, 60.0)]),
    ("Three months later came the Bay of Pigs. Over fourteen hundred Cuban exiles, trained and funded by the CIA, landed on Cuba's southern "
     "coast. Within three days, they were defeated. More than twelve hundred were captured.",
     [("v", INVADED, 3.0, 17.0), ("v", INVADED, 98.0, 111.0), ("v", INVADED, 113.0, 127.0)]),
    ("For President Kennedy, it was a public humiliation. For his military chiefs, the problem of Cuba was still unsolved.",
     [("v", RT, 53.0, 70.0), ("ph", f"{LOC}/jfk_jcs.tif")]),

    ("Ninety miles from Florida sat a country that had become a Soviet ally. And on its southeastern tip, the United States still held a naval "
     "base it had controlled since 1903: Guantanamo Bay.",
     [("ph", f"{LOC}/gitmo_aerial.tif"), ("ph", f"{LOC}/gitmo_troops.tif")]),
    ("card", "2 · LOOKING FOR A PRETEXT"),
    ("In November 1961, Kennedy authorized a secret campaign against Castro: Operation Mongoose, led by Air Force general Edward Lansdale. "
     "Its goal was an open revolt in Cuba by October 1962.",
     [("v", SCARE, 24.0, 36.0), ("v", CASTRO, 36.0, 50.0), ("v", INVADED, 120.0, 127.0)]),
    ("But the military doubted that revolt would ever come. On March 7, 1962, the Joint Chiefs put it in writing: if a credible internal revolt "
     "proved impossible, the United States would have to develop a Cuban provocation as justification for military action.",
     [("pg", "p14", [(0.355, 0.47)]), ("v", CC, 98.0, 102.5)]),
    ("The ideas began arriving early. On February 2, 1962, a memo sent to Lansdale proposed a plan called Operation Bingo: an incident "
     "staged at American facilities in Cuba, to be blamed on Castro.",
     [("ph", f"{LOC}/gitmo_bunker.tif"), ("v", SCARE, 19.0, 30.0)]),
    ("Even the space program was considered. As John Glenn prepared to orbit the Earth in February 1962, one proposal, known as Operation "
     "Dirty Trick, suggested that if his flight failed, the blame could be placed on Cuba.",
     [("v", GLENN, 7.0, 14.0), ("v", GLENN, 100.0, 125.0), ("v", GLENN, 150.0, 175.0)]),

    ("card", "3 · THE MEMO"),
    ("Lansdale asked for ideas. The Joint Chiefs delivered them. On March 13, 1962, their chairman, General Lyman Lemnitzer, signed the "
     "memorandum and sent it to Secretary of Defense Robert McNamara.",
     [("pgk", "subject"), ("ph", f"{LOC}/mcnamara.tif"), ("pgk", "signature")]),
    ("The memo called its proposals a preliminary submission, suitable only for planning purposes. But the goal was spelled out clearly: actions "
     "designed to lead inexorably to the objective of adequate justification for US military intervention in Cuba.",
     [("pg", "p09", [(0.12, 0.15)]), ("pg", "p09", [(0.28, 0.345)])]),

    ("Its cover note went further. It recommended that a single agency take charge of both overt and covert military operations, and that "
     "this agency be the Joint Chiefs of Staff themselves.",
     [("pg", "p00", [(0.515, 0.60)]), ("ph", f"{LOC}/jfk_jcs.tif")]),
    ("Attached was an annex with a blunt title: Pretexts to justify US military intervention in Cuba. What followed was a list.",
     [("pg", "p09", [(0.078, 0.095)])]),
    ("card", "4 · THE PRETEXTS"),
    ("The first ideas centered on Guantanamo Bay, the American naval base in Cuba. Friendly Cubans in uniform would stage an attack on the base. "
     "Saboteurs would blow up ammunition, burn aircraft and set ships on fire.",
     [("ph", f"{LOC}/gitmo_aerial.tif"), ("pg", "p09", [(0.70, 0.765)]), ("ph", f"{LOC}/gitmo_guards.tif"), ("ph", f"{LOC}/gitmo_bunker.tif")]),
    ("And then, the memo said, they would conduct funerals for mock victims.", [("pgk", "funerals")]),
    ("Another idea reached back to 1898, when the battleship Maine exploded in Havana harbor and America went to war with Spain. "
     "We could blow up a US ship in Guantanamo Bay and blame Cuba, the memo said. Casualty lists in US newspapers would cause a helpful "
     "wave of national indignation.",
     [("ph", f"{LOC}/maine1.tif"), ("pgk", "ship"), ("v", CC, 51.5, 66.0), ("pgk", "indignation")]),
    ("The plan went further. We could develop a Communist Cuban terror campaign in the Miami area, in other Florida cities and even in "
     "Washington. It suggested sinking a boatload of Cubans headed for Florida, real or simulated, and exploding plastic bombs in carefully "
     "chosen spots.",
     [("pgk", "terror"), ("v", MIA, 54.0, 66.0), ("pg", "p11", [(0.10, 0.145)]), ("pg", "p11", [(0.195, 0.215)])]),
    ("American pilots could fly look-alike Cuban MIG fighters. An F-86, properly painted, would convince air passengers they had seen a Cuban MIG.",
     [("v", CC, 145.5, 153.0), ("pg", "p11", [(0.72, 0.76)])]),
    ("Cuba's neighbors were part of the plan too. The memo proposed simulating a Castro-backed invasion of another Caribbean nation, and night "
     "raids on the Dominican Republic's sugar cane fields by aircraft painted to look Cuban, with Soviet bloc incendiaries left behind to be found.",
     [("pg", "p11", [(0.29, 0.40)]), ("v", INVADED, 3.0, 17.0), ("pg", "p11", [(0.47, 0.545)])]),
    ("Real copies of Cuban MIG fighters, it estimated, could be built from US resources in about three months.",
     [("pg", "p11", [(0.82, 0.87)])]),
    ("And then there was the airliner. A plane at Eglin Air Force Base would be painted as an exact copy of a civilian charter flight. "
     "The passengers, the memo suggested, could be a group of college students.",
     [("v", JET, 0.3, 2.6), ("pgk", "airliner"), ("pgk", "students")]),
    ("In mid-air, the two planes would switch. The real passengers would land secretly back at Eglin. The empty copy, now a drone, would fly "
     "on over Cuba, broadcast a mayday saying it was under attack by Cuban MIGs, and be destroyed by radio signal.",
     [("v", JET, 51.5, 53.8), ("pgk", "drone"), ("v", CC, 160.0, 186.0)]),
    ("One more scenario targeted the Air Force itself. A squadron of F-101 jets would fly from Homestead Air Force Base toward Cuba. One pilot "
     "would radio that he had been jumped by MIGs and was going down. He would then fly home low, under radar, while a submarine or boat "
     "scattered aircraft parts in the sea.",
     [("pg", "p13", [(0.195, 0.24)]), ("v", GLENN, 223.0, 250.0)]),
    ("To the world, it would look as if Cuba had shot down a plane full of American students.", [("neg",), ("v", JET, 0.3, 2.6)]),

    ("card", "5 · THE PRESIDENT SAYS NO"),
    ("On March 16, three days after the memo was signed, Lemnitzer met with President Kennedy. According to Lansdale's notes, Lemnitzer said "
     "the military had plans for creating pretexts. The President said bluntly that they were not discussing the use of military force.",
     [("ph", f"{LOC}/jfk_lemnitzer.tif"), ("v", RT, 75.0, 90.0)]),
    ("Northwoods was never carried out. Kennedy removed Lemnitzer as chairman of the Joint Chiefs, and in January 1963 he became NATO's "
     "Supreme Allied Commander in Europe.",
     [("ph", f"{LOC}/jfk_lemnitzer.tif"), ("ph", f"{LOC}/jfk_jcs.tif")]),
    ("Seven months after the memo, in October 1962, the world came closer to nuclear war than ever before, over Cuba.",
     [("v", RT, 4.0, 30.0), ("v", CC, 57.5, 66.0), ("v", CC, 160.0, 186.0)]),

    ("card", "6 · THIRTY-FIVE YEARS"),
    ("The memo went into the files, and for decades it stayed classified.", [("pgk", "topsecret")]),
    ("On November 18, 1997, the John F. Kennedy Assassination Records Review Board released it, along with 1,521 pages of records "
     "from 1962 to 1964.",
     [("stamp", "p13", "DECLASSIFIED"), ("pgk", "northwoods")]),
    ("Few people noticed. Only in 2001, when journalist James Bamford described it in his book Body of Secrets, did Operation Northwoods "
     "become widely known.",
     [("pgk", "subject"), ("pgk", "terror")]),

    ("The release showed that Northwoods was not an isolated idea. A 1963 Pentagon paper discussed a contrived Cuban attack on a member of the "
     "Organization of American States, and named Jamaica and Trinidad and Tobago as possible targets for covert action.",
     [("pgk", "terror"), ("v", INVADED, 46.0, 80.0)]),
    ("card", "7 · WHAT IT MEANS"),
    ("Northwoods is not a theory. It is a signed document, now public, that anyone can read.", [("pgk", "signature"), ("pgk", "northwoods")]),
    ("It does not show that any of these attacks happened. A president said no, and the plan died on paper.",
     [("v", RT, 75.0, 90.0)]),
    ("But it shows something harder to forget. In 1962, at the highest level of the American military, staging attacks and blaming an "
     "enemy was written down as a plan.",
     [("pgk", "ship"), ("pgk", "students"), ("pgk", "drone")]),
    ("How many plans like it are still in the files? If you want more declassified stories like this one, subscribe to Stunning Revelations.",
     [("stamp", "p00", "TOP SECRET")]),
]
