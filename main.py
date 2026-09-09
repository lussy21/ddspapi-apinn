    away = match.get("runner_away")
    event_id = match.get("event_id")
    league_name = match.get("league_name") or ""

    moneyline = (match.get("odds") or {}).get("moneyline") or {}
    odd1 = moneyline.get("odds1")
    odd2 = moneyline.get("odds2")

    if not odd1 or not odd2:
        continue

    favorite = "1" if odd1 < odd2 else "2"
    fav_side = "H" if favorite == "1" else "A"
    fav_odd = odd1 if favorite == "1" else odd2
    event_id_text = str(event_id)

    odds_response = requests.get(
        ODDS_URL,
        headers=HEADERS,
        params={"event_id": event_id},
        timeout=30,
    )
    odds_response.raise_for_status()
    event_odds = odds_response.json()

    contra = None

    if isinstance(event_odds, list):
        for asian in event_odds:
            if asian.get("market") != "spread":
                continue
            if asian.get("period") != 0:
                continue

            if favorite == "1" and asian.get("line") == -0.5:
                contra = asian.get("odds2")
                break

            if favorite == "2" and asian.get("line") == 0.5:
                contra = asian.get("odds1")
                break

    print(
        kickoff.strftime("%d/%m %H:%M"),
        "|", home, "vs", away,
        "| 1:", odd1,
        "| 2:", odd2,
        "| ΦΑΒΟΡΙ:", favorite,
        "| ΚΟΝΤΡΑ +0.5:", contra,
        "| event:", event_id,
    )

    if event_id_text in event_rows:
        row_number = event_rows[event_id_text]
    else:
        row_number = next_row
        next_row += 1
        event_rows[event_id_text] = row_number

        new_row = [
            league_name,
            home,
            away,
            fav_side,
            "", "", "",
            "", "", "",
            "", "", "", "",
            "", "", "",
            event_id_text,
        ]

        updates.append({
            "range": f"A{row_number}:R{row_number}",
            "values": [new_row],
        })

        while len(sheet_rows) < row_number:
            sheet_rows.append([])
        sheet_rows[row_number - 1] = new_row

        print("SHEET ROW CREATED:", row_number, home, "vs", away)

    current_row = sheet_rows[row_number - 1] if row_number <= len(sheet_rows) else []
    open_already = len(current_row) >= 5 and current_row[4] != ""
    min90_already = len(current_row) >= 6 and current_row[5] != ""

    minutes_to_kickoff = (kickoff - NOW).total_seconds() / 60

    # OPEN: γράφεται μία φορά γύρω στις 11:00.
    if NOW.hour == 11 and NOW.minute < 20 and not open_already:
        updates.append({"range": f"E{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"H{row_number}",
            "values": [["" if contra is None else contra]],
        })

    # 90MIN: γράφεται μία φορά περίπου 90 λεπτά πριν.
    if 85 <= minutes_to_kickoff <= 95 and not min90_already:
        updates.append({"range": f"F{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"I{row_number}",
            "values": [["" if contra is None else contra]],
        })

    # CLOSE: από τις 11:00 και μετά ανανεώνεται σε κάθε run μέχρι τη σέντρα.
    if NOW >= DAY_START and minutes_to_kickoff > 0:
        updates.append({"range": f"G{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"J{row_number}",
            "values": [["" if contra is None else contra]],
        })

if updates:
    SHEET.batch_update(
        updates,
        value_input_option="USER_ENTERED",
    )
    print("SHEET UPDATED:", len(updates), "ranges")
else:
    print("NO SHEET UPDATES NEEDED")
