-- =============================================================
-- SCRUM-89: Demo data for the Consumer App (Ask Sweetlife Flora)
-- 8 published plant care answers for the existing creator creator@gmail.com, and the existing
-- consumer user@gmail.com with 2 of 5 free answers used and 3 questions at different stages.
-- Does not create accounts or change roles. Stops with an error if an account is missing or
-- user@gmail.com is not a consumer.
-- Safe to re-run: fixed ids, so a second run updates the same rows instead of adding new ones.
-- Run in Supabase SQL Editor AFTER 20261014_008_consumer_read_policies.sql (needs the title column)
-- =============================================================

do $seed$
declare
  v_creator_id      uuid;
  v_creator_count   int;
  v_profile_id      uuid;
  v_role            text;
  v_consumer_id     uuid;
begin
  -- -----------------------------------------------------------
  -- Accounts
  -- -----------------------------------------------------------

  select count(*) into v_creator_count
  from auth.users u
  join public.creators c on c.profile_id = u.id
  where lower(u.email) = 'creator@gmail.com';

  if v_creator_count = 0 then
    raise exception 'Seed stopped: no creators row for creator@gmail.com. Create that creator first.';
  elsif v_creator_count > 1 then
    raise exception 'Seed stopped: creator@gmail.com has % creators rows, expected 1.', v_creator_count;
  end if;

  select c.id into v_creator_id
  from auth.users u
  join public.creators c on c.profile_id = u.id
  where lower(u.email) = 'creator@gmail.com';

  select u.id, p.role into v_profile_id, v_role
  from auth.users u
  left join public.profiles p on p.id = u.id
  where lower(u.email) = 'user@gmail.com';

  if v_profile_id is null then
    raise exception 'Seed stopped: no account for user@gmail.com. Create it in Authentication > Users first.';
  end if;

  if v_role is distinct from 'consumer' then
    raise exception 'Seed stopped: user@gmail.com has role %, expected consumer. This seed does not change roles.',
      coalesce(v_role, '(no profile)');
  end if;

  select id into v_consumer_id
  from public.consumers
  where profile_id = v_profile_id
  order by id
  limit 1;

  if v_consumer_id is null then
    insert into public.consumers (profile_id, free_views_used, auth_provider)
    values (v_profile_id, 2, 'email')
    returning id into v_consumer_id;
  else
    update public.consumers set free_views_used = 2 where id = v_consumer_id;
  end if;

  -- -----------------------------------------------------------
  -- Published knowledge entries
  -- -----------------------------------------------------------

  insert into public.knowledge_entries (id, creator_id, source, title, content, tags, published)
  values
  (
    '89000000-0000-4000-8000-000000000001', v_creator_id, 'question',
    'Why are the lower leaves on my pothos turning yellow?',
    $t$A few yellow leaves at the bottom of a pothos are usually one of two things.

If it's one or two of the oldest leaves and the rest of the plant looks healthy, that's normal. Pothos drop old leaves as they put energy into new growth. Snip them off and move on.

If several leaves are going yellow at once, especially with soft stems or soil that stays damp for days, it's almost always too much water. Push a finger two inches into the soil. Only water when that depth feels dry, and always empty the cachepot or saucer 15 minutes after watering so the roots aren't sitting in water.

Yellow leaves with crispy brown edges point the other way: the plant dried out completely. Water thoroughly until it runs out the drainage hole, then check the soil every few days.

Bright, indirect light helps too. A pothos in a dark corner uses water slowly, which makes overwatering more likely.$t$,
    array['yellow leaves', 'overwatering'], true
  ),
  (
    '89000000-0000-4000-8000-000000000002', v_creator_id, 'question',
    'How do I get rid of fungus gnats in my houseplants?',
    $t$Fungus gnats are the tiny black flies hovering around your pots. The adults are harmless, but their larvae live in the top inch of wet soil and feed on roots and organic matter, so the fix is to break their life cycle.

1. Let the top one to two inches of soil dry out completely between waterings. The larvae need constant moisture to survive.
2. Put yellow sticky traps flat on the soil surface to catch adults before they lay more eggs.
3. Water with BTI (sold as mosquito bits or mosquito dunks) for three waterings in a row. It's a natural bacteria that kills the larvae and is safe for plants and pets.
4. Bottom water for a few weeks if you can, so the surface stays dry.

Expect it to take two to three weeks, because eggs already in the soil keep hatching. If the problem keeps coming back, repot into fresh, chunkier soil that drains faster.$t$,
    array['fungus gnats', 'pests'], true
  ),
  (
    '89000000-0000-4000-8000-000000000003', v_creator_id, 'question',
    'When should I repot my monstera, and how do I know it needs it?',
    $t$Repot in spring or early summer, when the plant is actively growing and recovers fastest.

Signs it's time:
- Roots circling the bottom of the pot or growing out of the drainage holes
- Water runs straight through without soaking in
- The plant dries out much faster than it used to
- New leaves are coming in smaller than older ones

Go up only one pot size, about two inches wider than the current pot. A pot that's too big holds extra wet soil around the roots and invites root rot. Make sure it has a drainage hole.

Use an airy mix: roughly equal parts potting soil, orchid bark and perlite. Loosen the root ball gently, trim any black or mushy roots, set it at the same depth it was before, and water well. Keep it out of direct sun for a week while it settles in.$t$,
    array['repotting', 'soil'], true
  ),
  (
    '89000000-0000-4000-8000-000000000004', v_creator_id, 'question',
    'How can I tell if I''m overwatering my plant?',
    $t$Overwatering is the most common way houseplants die, and it's really about roots not getting air rather than the amount of water.

Warning signs:
- Soil still damp several days after watering
- Yellow, soft or droopy leaves even though the soil is wet
- Mushy, dark stems near the soil line
- A sour or rotten smell from the pot
- Fungus gnats hanging around

What to do:
1. Stop watering and let the soil dry well down into the pot.
2. If the smell is bad or stems are mushy, slide the plant out and check the roots. Healthy roots are firm and white or tan. Rotten ones are brown, slimy and pull apart easily. Cut those off with clean scissors and repot in fresh, fast-draining soil.
3. Going forward, water by checking the soil, not by the calendar. Most houseplants want water when the top one to two inches are dry.

A pot with a drainage hole matters more than anything else here.$t$,
    array['overwatering', 'yellow leaves'], true
  ),
  (
    '89000000-0000-4000-8000-000000000005', v_creator_id, 'question',
    'What are the best plants for a room with low light?',
    $t$"Low light" usually means a spot several feet from a window, or a north-facing room. These handle it well:

- Snake plant: tough, slow, and happy with water every two to three weeks
- ZZ plant: glossy leaves, stores water in its roots, very forgiving
- Pothos: grows more slowly in low light but stays healthy
- Cast iron plant: lives up to its name
- Peace lily: tells you when it's thirsty by drooping, then perks right up after a drink

Two tips that matter more than the plant choice:
1. Water less. Plants in low light use water slowly, so the soil stays wet longer. Always check before watering.
2. Dust the leaves every month or so. A dusty leaf catches even less of the little light it gets.

No plant grows in a room with no window at all unless you add a grow light.$t$,
    array['low light'], true
  ),
  (
    '89000000-0000-4000-8000-000000000006', v_creator_id, 'question',
    'There are tiny webs on my plant. Is it spider mites?',
    $t$Fine webbing between leaves and stems, plus tiny pale speckles on the leaves, is a classic sign of spider mites. To check, hold a white sheet of paper under a leaf and tap it. If tiny dots start moving, that's them.

Act quickly, because they multiply fast in warm, dry air:
1. Move the plant away from your other plants.
2. Rinse it thoroughly in the shower, including the undersides of every leaf.
3. Wipe the leaves with a soft cloth, then spray every surface with insecticidal soap or diluted neem oil. Do this in the evening, out of direct sun.
4. Repeat every five to seven days for at least three weeks. One treatment never gets the eggs.

Raising the humidity helps keep them from coming back, since spider mites hate moist air. Check new plants carefully before bringing them home.$t$,
    array['pests'], true
  ),
  (
    '89000000-0000-4000-8000-000000000007', v_creator_id, 'question',
    'How do I propagate pothos in water?',
    $t$Pothos is one of the easiest plants to propagate.

1. Find a node: the small brown bump on the stem where a leaf meets it. Roots grow from nodes, not from leaves.
2. Cut just below a node with clean scissors. A cutting with two or three nodes and a few leaves works best.
3. Remove any leaf that would sit underwater, so it doesn't rot.
4. Put the cutting in a glass of room temperature water with the nodes submerged, and set it in bright, indirect light.
5. Change the water every week.

Roots usually show up in one to two weeks. Once they're two to three inches long, plant the cutting in moist, well-draining soil and keep the soil a little damp for the first couple of weeks while the roots adjust from water to soil.

For a fuller plant, pot several cuttings together.$t$,
    array['propagation'], true
  ),
  (
    '89000000-0000-4000-8000-000000000008', v_creator_id, 'question',
    'What kind of soil should I use for my houseplants?',
    $t$Most houseplants do best in soil that holds some moisture but lets air reach the roots. Bagged potting mix alone is often too dense, so improve it:

- Most tropical plants (pothos, philodendron, monstera): two parts potting mix, one part orchid bark, one part perlite.
- Succulents, cacti and snake plants: half potting mix, half perlite or coarse sand. They need to dry out fast.
- Ferns and calatheas: potting mix with a little extra coco coir to hold moisture, plus some perlite.

Never use garden soil indoors. It packs down hard in a pot, drains poorly and can bring in pests.

Signs your soil isn't working: water pools on top, the pot stays wet for a week, or the soil pulls away from the sides when dry. That's a good time to repot into a fresh mix.$t$,
    array['soil', 'repotting'], true
  )
  on conflict (id) do update set
    creator_id = excluded.creator_id,
    source     = excluded.source,
    title      = excluded.title,
    content    = excluded.content,
    tags       = excluded.tags,
    published  = excluded.published;

  -- -----------------------------------------------------------
  -- The consumer's questions: waiting, answered inside the hold, accepted
  -- -----------------------------------------------------------

  insert into public.questions (
    id, creator_id, source, consumer_id, question_text, status,
    price_cents, followups_included, paid_at, delivered_at, hold_ends_at, accepted_at
  )
  values
  (
    '89000000-0000-4000-8000-000000000101', v_creator_id, 'knowledge_app', v_consumer_id,
    'My fiddle leaf fig dropped three leaves this week after I moved it closer to the window. Should I move it back?',
    'awaiting_creator', 500, 3, now() - interval '2 hours', null, null, null
  ),
  (
    '89000000-0000-4000-8000-000000000102', v_creator_id, 'knowledge_app', v_consumer_id,
    'There are tiny white fuzzy spots on the undersides of my hoya leaves. What are they and how do I get rid of them?',
    'delivered', 500, 3, now() - interval '2 days', now() - interval '1 day', now() + interval '2 days', null
  ),
  (
    '89000000-0000-4000-8000-000000000103', v_creator_id, 'knowledge_app', v_consumer_id,
    'How often should I water my snake plant in winter?',
    'accepted', 500, 3, now() - interval '10 days', now() - interval '9 days', now() - interval '6 days',
    now() - interval '8 days'
  )
  on conflict (id) do update set
    creator_id         = excluded.creator_id,
    source             = excluded.source,
    consumer_id        = excluded.consumer_id,
    question_text      = excluded.question_text,
    status             = excluded.status,
    price_cents        = excluded.price_cents,
    followups_included = excluded.followups_included,
    paid_at            = excluded.paid_at,
    delivered_at       = excluded.delivered_at,
    hold_ends_at       = excluded.hold_ends_at,
    accepted_at        = excluded.accepted_at;

  insert into public.drafts (id, question_id, final_text, status, approved_at)
  values
  (
    '89000000-0000-4000-8000-000000000202', '89000000-0000-4000-8000-000000000102',
    $t$Those white fuzzy spots are mealybugs. They're a common hoya pest and very treatable.

Isolate the hoya from your other plants, then dab every spot you can see with a cotton swab dipped in rubbing alcohol. Check the leaf undersides, the stems and where leaves join the vine, because they love to hide there.

After that, spray the whole plant with insecticidal soap and repeat every 5 to 7 days for three weeks to catch any new ones as they hatch. Keep an eye out for a couple of weeks after it looks clear.$t$,
    'approved', now() - interval '1 day 1 hour'
  ),
  (
    '89000000-0000-4000-8000-000000000203', '89000000-0000-4000-8000-000000000103',
    $t$In winter, about once every 4 to 6 weeks is plenty. Snake plants grow very slowly in the cooler, darker months and use very little water.

Water only when the soil is completely dry all the way down, and water thoroughly so it drains out the bottom. If you're not sure, wait another week. A thirsty snake plant is fine. One that sits in wet soil in winter is the main way they get root rot.$t$,
    'approved', now() - interval '9 days 1 hour'
  )
  on conflict (id) do update set
    question_id = excluded.question_id,
    final_text  = excluded.final_text,
    status      = excluded.status,
    approved_at = excluded.approved_at;

  raise notice 'Consumer demo data ready: creator %, consumer %', v_creator_id, v_consumer_id;
end;
$seed$;
