# EmeraldTogether: Windows test checklist for the Update 15-20 build

Adds to `docs/windows-test-update8-14.md` and `docs/windows-test-update2-7.md`. **Nothing below has been run on a real PC.** The
features were tested only by unit tests, engine self-tests, the GBA test ROM and a real host with scripted game bridges
(`DEVELOPMENT_LEDGER.md` Updates 15-20, `docs/automated-validation-matrix.md`). bios.c licensing is unresolved: this build is for the
owner's private testing only.

## A. NEW: four-player free-for-all, 1v1v1v1 (four PCs; PLAYERS > Challenges > Free-for-all 1v1v1v1)

Four players connected, each with a saved party. The launcher *Battle* panel also offers "Review 1v1v1v1 free-for-all with ...".
- [ ] The challenger picks **Free-for-all 1v1v1v1**; the other three see "1v1v1v1 free-for-all" under *Pending challenge* with the four names and party sizes, and **no wager row**. Each of the three presses **Accept challenge** (nobody's consent is inherited). When all four accepted, each presses **Enter battle**.
- [ ] The battle shows four Pokémon (doubles screen layout; the third foe is drawn in the partner slot). Each player is asked for their own Pokémon's move; **a move can be aimed at any of the other three**; there is no Run and no partner.
- [ ] Spread moves hit all three others (Swift, Surf, Earthquake); Intimidate lowers all three; a hazard (Spikes) lands only on the trainer it was aimed at; Reflect protects only its user; Helping Hand fails.
- [ ] A trainer whose last Pokémon faints is out and keeps watching; the others fight on; the last trainer standing wins ("You won!" for that player, "lost" for the others). If the last two fall on the same turn it is a draw.
- [ ] No EXP and no money change for anybody. After the battle everybody returns to the overworld with their own party unchanged (their original save), and a second challenge works.
- [ ] Close one game in the middle of the battle and reopen it: the **Recover battle** path resumes the same battle (same as a 2v2); no duplicate result is recorded (`ffa_results` in the host database keeps one row per battle).
- [ ] Look for: wrong names in messages ("The opposing X" is expected for every foe), a trainer sprite in a wrong place, a missing health box, a stuck menu when two players switch on the same turn.

## B. NEW: complete Battle Frontier (two PCs; PLAYERS > World and my base > Frontier and League > Battle Frontier)

Each player needs a saved party of **more than 3 Pokémon** for the team-selection checks (save in game, stay connected).
- [ ] *Team, BP shop* > **Team** lists your saved party; tap three Pokémon (a fourth tap gives up the first). Start a run; in the battle each player has **only their chosen Pokémon** (their order is the saved order). After the battle (win or lose) open your party: **all your Pokémon are back, nothing missing, HP and moves as before the battle**.
- [ ] Change the team between rounds; round 2 uses the new team. Deposit a chosen Pokémon in the PC and try again: the host falls back to the first three (the Team page says "(auto)").
- [ ] Clear a round: a banner "ROUND N CLEARED! ... +N BP". Each player's **Battle Points** (Pokémon Center's Battle Frontier BP counter / the game's Exchange Service Corner, or any BP display) went up by exactly that amount **once**, even after reconnecting or restarting the host.
- [ ] Clear a Brain round (round 7) for the first time: the item prize (Rare Candy) is in the bag; clear it again in a later run: no item (BP only, halved).
- [ ] **BP shop**: buy a Protein (16 BP) with enough BP: BP drop by 16, the item appears; with too few BP the order is refused ("costs 16 BP"); with a full bag and a full PC the BP come back. One order at a time; close the game right after ordering and reopen it: the order completes once.
- [ ] A teammate who is offline when a round is cleared gets their BP and item the next time they connect (not twice).
- [ ] Spend the same BP at the real Battle Frontier Exchange Service Corner (if you have reached the Frontier): the numbers agree.

## C. NEW: legendary catch consistency (two PCs; start a legendary World Event)
Real-PC checks that are not done yet. Everything here was only simulated.
- [ ] Let both players battle the same legendary. Make one player's claim lapse (close that player's game for over a minute during the battle, then reopen it) so both can finish the battle. Both catch it.
- [ ] Exactly **one** player keeps the Pokémon. The other sees the message "X caught it first" and the second copy leaves their party/box after their game reconnects. No other Pokémon is removed or changed.
- [ ] The kept Pokémon keeps its shiny colour, level and held Mega Stone.
- [ ] Restart the host after the first report and before the second player reports: the same player still wins.
- [ ] A player with only that one Pokémon in the party is **not** left without a party (the release waits).
- [ ] Trade or evolve the second copy before reconnecting: nothing is removed, and the host log says why.
- [ ] Reconnect repeatedly: the release happens once, not twice.

## D. NEW: graphical PokéNav map (two or more PCs)
Everything here was only looked at in a headless Linux build; none of it is verified on Windows.
- [ ] Both PCs in the overworld on different routes. Open the PokéNav (Start > PokéNav > HOENN MAP). Your own icon is where you stand; the other player appears as a **coloured** copy of the trainer icon (Blue, Yellow, Purple or Orange) on the right route.
- [ ] PLAYERS > World and my base > Players and weather > that player: "Map icon: <colour>" matches the colour you see.
- [ ] Press **SELECT**: the cursor jumps to the other player and the name box shows their place; pressing it again goes to the next marker and then back.
- [ ] Walk the other player to another town while your map stays open: the marker follows within about two seconds.
- [ ] A in the map zooms in; markers sit on the right squares and scroll with the map; A again returns.
- [ ] Put the other player inside a Pokémon Center: the marker is on that town's square.
- [ ] While a World Event is on the map (awake), a flashing red square marks it; while a mass outbreak runs, a flashing pink dot marks its route. Both go away when the event/outbreak ends.
- [ ] The Pokémon Center wall map and the fly map show the same markers; leaving and re-entering the map shows no leftover or missing icons.
- [ ] 3D (Diorama) window: the map looks the same as in the 2D window.
- [ ] Four players on the same square: all four icons can be seen (fanned out).
