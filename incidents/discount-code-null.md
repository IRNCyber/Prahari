# Checkout null discount-code incident

When checkout failures are concentrated on requests without `discount_code`, inspect
the most recent deploy for a missing null guard. Add a regression case before fixing it.
