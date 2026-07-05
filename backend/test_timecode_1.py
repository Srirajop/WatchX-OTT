from timecoded_subtitles import parse_timecoded_subtitles

test_text = """
01:00:00 | SCENE A Title Sequence: Food Factory | 
01:00:13 | Actuality: Cart full with filling with pump; filling being piped onto pastry, various shots; pastry being rolled around filling by large roller, various shots; worker taking pastry rolls and winding them on plate, various shots; baked twister | We take a spin to check out this Greek classic's modern twist.
01:00:19 | Actuality: Worker covering base of chocolate cake with praline bits, various shots; worker | One company doubles down on a cake inside a cake.
"""

print(parse_timecoded_subtitles(test_text))
