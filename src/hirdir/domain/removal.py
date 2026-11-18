"""Several items or device groups retired at once, and an Admin's deletion of those that
were a mistake (P-227, P-228, P-236)."""

# How many records one request retires or deletes, at most.
MOST_AT_ONCE = 1000
