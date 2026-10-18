-- The rules Monelyth ships with (PLAN.md 3.3), matched to the default categories by name.
--
-- How rules match (monelyth_engine.categorize.rules): a 'contains' pattern matches whole words
-- of the cleaned merchant name or the bank's description, ignoring case, accents and
-- punctuation, so 'tim hortons' matches "TIM HORTONS #2231" but 'bar' never matches "BARBER".
-- 'regex' patterns are searched case-insensitively in the same two texts.
--
-- Priorities: when several rules match, the highest priority wins. Rules the user makes always
-- beat these. The levels used here:
--   20  a more specific phrase that must beat a shorter one ('uber eats' over 'uber')
--   10  a merchant or brand name
--    0  a generic word ('pharmacy', 'parking'), the last resort
--
-- Every row must name an existing default category; a test checks none is dropped by the join.
-- The migration runner wraps this file in a transaction; do not add BEGIN or COMMIT here.

WITH defaults (pattern, match_type, category, priority) AS (VALUES
  -- Income
  ('payroll',                    'contains', 'Salary',            10),
  ('salary',                     'contains', 'Salary',             0),
  ('tax refund',                 'contains', 'Other Income',      10),
  ('e transfer from',            'contains', 'Other Income',      20),
  ('cash back reward',           'contains', 'Other Income',      10),

  -- Housing and bills
  ('rent',                       'contains', 'Rent/Mortgage',      0),
  ('mortgage',                   'contains', 'Rent/Mortgage',      0),
  ('property mgmt',              'contains', 'Rent/Mortgage',     10),
  ('property management',        'contains', 'Rent/Mortgage',     10),
  ('hydro',                      'contains', 'Utilities',          0),
  ('enbridge',                   'contains', 'Utilities',         10),
  ('bell canada',                'contains', 'Utilities',         10),
  ('rogers',                     'contains', 'Utilities',         10),
  ('telus',                      'contains', 'Utilities',         10),
  ('fido',                       'contains', 'Utilities',         10),
  ('koodo',                      'contains', 'Utilities',         10),
  ('freedom mobile',             'contains', 'Utilities',         10),
  ('virgin plus',                'contains', 'Utilities',         10),
  ('videotron',                  'contains', 'Utilities',         10),
  ('comcast',                    'contains', 'Utilities',         10),
  ('verizon',                    'contains', 'Utilities',         10),

  -- Groceries
  ('loblaws',                    'contains', 'Groceries',         10),
  ('no frills',                  'contains', 'Groceries',         10),
  ('sobeys',                     'contains', 'Groceries',         10),
  ('safeway',                    'contains', 'Groceries',         10),
  ('freshco',                    'contains', 'Groceries',         10),
  ('food basics',                'contains', 'Groceries',         10),
  ('farm boy',                   'contains', 'Groceries',         10),
  ('real canadian superstore',   'contains', 'Groceries',         10),
  ('t&t supermarket',            'contains', 'Groceries',         10),
  ('costco',                     'contains', 'Groceries',         10),
  ('whole foods',                'contains', 'Groceries',         10),
  ('trader joe''s',              'contains', 'Groceries',         10),
  ('instacart',                  'contains', 'Groceries',         10),
  ('supermarket',                'contains', 'Groceries',          0),
  ('grocery',                    'contains', 'Groceries',          0),
  ('fruit market',               'contains', 'Groceries',          0),

  -- Eating out
  ('uber eats',                  'contains', 'Dining Out',        20),
  ('ubereats',                   'contains', 'Dining Out',        20),
  ('doordash',                   'contains', 'Dining Out',        10),
  ('skipthedishes',              'contains', 'Dining Out',        10),
  ('skip the dishes',            'contains', 'Dining Out',        10),
  ('mcdonald''s',                'contains', 'Dining Out',        10),
  ('burger king',                'contains', 'Dining Out',        10),
  ('wendy''s',                   'contains', 'Dining Out',        10),
  ('harvey''s',                  'contains', 'Dining Out',        10),
  ('kfc',                        'contains', 'Dining Out',        10),
  ('popeyes',                    'contains', 'Dining Out',        10),
  ('chipotle',                   'contains', 'Dining Out',        10),
  ('subway',                     'contains', 'Dining Out',        10),
  ('pizza',                      'contains', 'Dining Out',         0),
  ('sushi',                      'contains', 'Dining Out',         0),
  ('taco',                       'contains', 'Dining Out',         0),
  ('noodle',                     'contains', 'Dining Out',         0),
  ('restaurant',                 'contains', 'Dining Out',         0),
  ('tavern',                     'contains', 'Dining Out',         0),
  ('pub',                        'contains', 'Dining Out',         0),
  ('bistro',                     'contains', 'Dining Out',         0),
  ('starbucks',                  'contains', 'Coffee',            10),
  ('tim hortons',                'contains', 'Coffee',            10),
  ('second cup',                 'contains', 'Coffee',            10),
  ('blue bottle',                'contains', 'Coffee',            10),
  ('dunkin',                     'contains', 'Coffee',            10),
  ('coffee',                     'contains', 'Coffee',             0),
  ('cafe',                       'contains', 'Coffee',             0),
  ('espresso',                   'contains', 'Coffee',             0),

  -- Getting around
  ('presto',                     'contains', 'Transport',         10),
  ('ttc',                        'contains', 'Transport',         10),
  ('go transit',                 'contains', 'Transport',         10),
  ('green p',                    'contains', 'Transport',         10),
  ('impark',                     'contains', 'Transport',         10),
  ('parking',                    'contains', 'Transport',          0),
  ('transit',                    'contains', 'Transport',          0),
  ('petro canada',               'contains', 'Gas',               10),
  ('shell',                      'contains', 'Gas',               10),
  ('esso',                       'contains', 'Gas',               10),
  ('husky',                      'contains', 'Gas',               10),
  ('ultramar',                   'contains', 'Gas',               10),
  ('chevron',                    'contains', 'Gas',               10),
  ('costco gas',                 'contains', 'Gas',               20),
  ('canadian tire gas',          'contains', 'Gas',               20),
  ('gas bar',                    'contains', 'Gas',                0),
  ('uber',                       'contains', 'Rideshare',         10),
  ('lyft',                       'contains', 'Rideshare',         10),
  ('taxi',                       'contains', 'Rideshare',          0),

  -- Shopping
  ('amazon',                     'contains', 'Shopping',          10),
  ('amzn',                       'contains', 'Shopping',          10),
  ('best buy',                   'contains', 'Shopping',          10),
  ('winners',                    'contains', 'Shopping',          10),
  ('homesense',                  'contains', 'Shopping',          10),
  ('ikea',                       'contains', 'Shopping',          10),
  ('canadian tire',              'contains', 'Shopping',          10),
  ('walmart',                    'contains', 'Shopping',          10),
  ('dollarama',                  'contains', 'Shopping',          10),
  ('home depot',                 'contains', 'Shopping',          10),
  ('indigo',                     'contains', 'Shopping',          10),
  ('ebay',                       'contains', 'Shopping',          10),
  ('etsy',                       'contains', 'Shopping',          10),

  -- Subscriptions and entertainment
  ('netflix',                    'contains', 'Subscriptions',     10),
  ('spotify',                    'contains', 'Subscriptions',     10),
  ('apple com bill',             'contains', 'Subscriptions',     20),
  ('amazon prime',               'contains', 'Subscriptions',     20),
  ('disney plus',                'contains', 'Subscriptions',     10),
  ('youtube premium',            'contains', 'Subscriptions',     10),
  ('icloud',                     'contains', 'Subscriptions',     10),
  ('cineplex',                   'contains', 'Entertainment',     10),
  ('ticketmaster',               'contains', 'Entertainment',     10),
  ('steampowered',               'contains', 'Entertainment',     10),

  -- Health and education
  ('shoppers drug mart',         'contains', 'Health',            10),
  ('rexall',                     'contains', 'Health',            10),
  ('pharmacy',                   'contains', 'Health',             0),
  ('dental',                     'contains', 'Health',             0),
  ('clinic',                     'contains', 'Health',             0),
  ('coursera',                   'contains', 'Education',         10),
  ('udemy',                      'contains', 'Education',         10),
  ('tuition',                    'contains', 'Education',          0),
  ('college',                    'contains', 'Education',          0),
  ('university',                 'contains', 'Education',          0),

  -- Travel
  ('air canada',                 'contains', 'Travel',            10),
  ('westjet',                    'contains', 'Travel',            10),
  ('porter airlines',            'contains', 'Travel',            10),
  ('airbnb',                     'contains', 'Travel',            10),
  ('expedia',                    'contains', 'Travel',            10),
  ('via rail',                   'contains', 'Travel',            10),
  ('rent a car',                 'contains', 'Travel',            20),
  ('hotel',                      'contains', 'Travel',             0),

  -- Fees, giving and money moving between accounts
  ('account fee',                'contains', 'Fees & Interest',   10),
  ('annual fee',                 'contains', 'Fees & Interest',   10),
  ('service charge',             'contains', 'Fees & Interest',   10),
  ('overdraft',                  'contains', 'Fees & Interest',   10),
  ('interest charge',            'contains', 'Fees & Interest',   10),
  ('canadahelps',                'contains', 'Gifts & Donations', 10),
  ('donation',                   'contains', 'Gifts & Donations',  0),
  ('florist',                    'contains', 'Gifts & Donations',  0),
  ('payment thank you',          'contains', 'Transfers',         20),
  ('payment received',           'contains', 'Transfers',         20),
  ('\bpayment\b.*\b(visa|mastercard|amex|credit card)\b',
                                 'regex',    'Transfers',         20),
  ('atm withdrawal',             'contains', 'Other',             10)
)
INSERT INTO rules (pattern, match_type, category_id, priority, created_by)
SELECT d.pattern, d.match_type, c.id, d.priority, 'system'
FROM defaults AS d
JOIN categories AS c ON c.name = d.category;
