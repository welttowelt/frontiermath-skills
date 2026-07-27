/*
 * Variable-neighborhood exact integer-PAF search inside LP333 family ID5.
 *
 * Seven eighths of proposals use the source ID5 equal-size orbit swap.
 * One eighth exchanges two negative and two positive triple-orbits at once,
 * flipping twelve coordinates while preserving subgroup invariance and all
 * forced row-sum margins.
 */
#define main lp333_pq2_baseline_main
#include "search_lp333_pq2_anneal.c"
#undef main

enum { DOUBLE_ID5_ORBITS = 113, DOUBLE_ID5_GENERATOR = 211 };

static int orbit_count;
static int orbit_size[DOUBLE_ID5_ORBITS];
static int orbit_members[DOUBLE_ID5_ORBITS][3];
static int coordinate_orbit[LENGTH];

static void build_id5_orbits(void) {
  for (int index = 0; index < LENGTH; ++index)
    coordinate_orbit[index] = -1;
  orbit_count = 0;
  for (int seed = 0; seed < LENGTH; ++seed) {
    if (coordinate_orbit[seed] >= 0)
      continue;
    int value = seed;
    int size = 0;
    do {
      if (size >= 3) {
        fprintf(stderr, "ID5 orbit exceeded order three\n");
        exit(2);
      }
      orbit_members[orbit_count][size++] = value;
      coordinate_orbit[value] = orbit_count;
      value = (value * DOUBLE_ID5_GENERATOR) % LENGTH;
    } while (value != seed);
    orbit_size[orbit_count++] = size;
  }
  int singletons = 0;
  int triples = 0;
  for (int orbit = 0; orbit < orbit_count; ++orbit) {
    singletons += orbit_size[orbit] == 1;
    triples += orbit_size[orbit] == 3;
  }
  if (orbit_count != DOUBLE_ID5_ORBITS ||
      singletons != 3 || triples != 110) {
    fprintf(stderr, "ID5 orbit signature changed\n");
    exit(2);
  }
}

static int double_id5_row_sum(const int8_t row[LENGTH]) {
  int result = 0;
  for (int index = 0; index < LENGTH; ++index)
    result += row[index];
  return result;
}

static int id5_invariance_and_sums_hold(const state_t *state) {
  for (int row = 0; row < ROWS; ++row) {
    if (double_id5_row_sum(state->values[row]) != 1)
      return 0;
    int negative_singletons = 0;
    int negative_triples = 0;
    for (int orbit = 0; orbit < orbit_count; ++orbit) {
      int8_t sign = state->values[row][orbit_members[orbit][0]];
      for (int item = 1; item < orbit_size[orbit]; ++item)
        if (state->values[row][orbit_members[orbit][item]] != sign)
          return 0;
      if (sign < 0) {
        negative_singletons += orbit_size[orbit] == 1;
        negative_triples += orbit_size[orbit] == 3;
      }
    }
    if (negative_singletons != 1 || negative_triples != 55)
      return 0;
  }
  return 1;
}

static void initialize_id5_row(int8_t row[LENGTH], rng_t *rng) {
  int singleton_ids[3];
  int triple_ids[110];
  int singletons = 0;
  int triples = 0;
  for (int orbit = 0; orbit < orbit_count; ++orbit) {
    if (orbit_size[orbit] == 1)
      singleton_ids[singletons++] = orbit;
    else
      triple_ids[triples++] = orbit;
  }
  for (int item = triples - 1; item > 0; --item) {
    int other = (int)(rng_next(rng) % (uint64_t)(item + 1));
    int temporary = triple_ids[item];
    triple_ids[item] = triple_ids[other];
    triple_ids[other] = temporary;
  }
  int negative_singleton =
      singleton_ids[rng_next(rng) % (uint64_t)singletons];
  for (int orbit = 0; orbit < orbit_count; ++orbit) {
    int8_t sign = orbit == negative_singleton ? -1 : 1;
    for (int item = 0; item < 55; ++item)
      if (orbit == triple_ids[item])
        sign = -1;
    for (int item = 0; item < orbit_size[orbit]; ++item)
      row[orbit_members[orbit][item]] = sign;
  }
}

static void initialize_id5_state(state_t *state, rng_t *rng) {
  initialize_id5_row(state->values[0], rng);
  initialize_id5_row(state->values[1], rng);
  refresh_objective(state);
}

static void choose_orbit_swap(const state_t *state, int row,
                              rng_t *rng, int positions[6],
                              int *count) {
  int size = rng_next(rng) % 8 == 0 ? 1 : 3;
  int negative[110];
  int positive[110];
  int negative_count = 0;
  int positive_count = 0;
  for (int orbit = 0; orbit < orbit_count; ++orbit) {
    if (orbit_size[orbit] != size)
      continue;
    int sign = state->values[row][orbit_members[orbit][0]];
    if (sign < 0)
      negative[negative_count++] = orbit;
    else
      positive[positive_count++] = orbit;
  }
  int left = negative[rng_next(rng) % (uint64_t)negative_count];
  int right = positive[rng_next(rng) % (uint64_t)positive_count];
  *count = 0;
  for (int item = 0; item < orbit_size[left]; ++item)
    positions[(*count)++] = orbit_members[left][item];
  for (int item = 0; item < orbit_size[right]; ++item)
    positions[(*count)++] = orbit_members[right][item];
}

static int double_id5_flipped_index(int index,
                                    const int positions[12],
                                    int count) {
  for (int item = 0; item < count; ++item)
    if (positions[item] == index)
      return 1;
  return 0;
}

static int double_id5_value_after_many(const int8_t row[LENGTH],
                                       int index,
                                       const int positions[12],
                                       int count) {
  int value = row[index];
  return double_id5_flipped_index(index, positions, count)
             ? -value
             : value;
}

static void double_id5_multiflip_delta(
    const int8_t row[LENGTH], const int positions[12], int count,
    int delta[HALF + 1]) {
  delta[0] = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    int starts[24];
    int start_count = 0;
    for (int item = 0; item < count; ++item) {
      starts[start_count++] = positions[item];
      starts[start_count++] = wrapped(positions[item] - shift);
    }
    int change = 0;
    for (int item = 0; item < start_count; ++item) {
      int start = starts[item];
      int duplicate = 0;
      for (int prior = 0; prior < item; ++prior)
        if (starts[prior] == start)
          duplicate = 1;
      if (duplicate)
        continue;
      int end = wrapped(start + shift);
      int old_product = row[start] * row[end];
      int new_product =
          double_id5_value_after_many(row, start, positions, count) *
          double_id5_value_after_many(row, end, positions, count);
      change += new_product - old_product;
    }
    delta[shift] = change;
  }
}

static void choose_two_distinct(const int values[110], int count,
                                rng_t *rng, int chosen[2]) {
  int first = (int)(rng_next(rng) % (uint64_t)count);
  int second = (int)(rng_next(rng) % (uint64_t)(count - 1));
  if (second >= first)
    ++second;
  chosen[0] = values[first];
  chosen[1] = values[second];
}

static void choose_double_triple_swap(const state_t *state, int row,
                                      rng_t *rng, int positions[12]) {
  int negative[110];
  int positive[110];
  int negative_count = 0;
  int positive_count = 0;
  for (int orbit = 0; orbit < orbit_count; ++orbit) {
    if (orbit_size[orbit] != 3)
      continue;
    int sign = state->values[row][orbit_members[orbit][0]];
    if (sign < 0)
      negative[negative_count++] = orbit;
    else
      positive[positive_count++] = orbit;
  }
  int negative_chosen[2];
  int positive_chosen[2];
  choose_two_distinct(negative, negative_count, rng, negative_chosen);
  choose_two_distinct(positive, positive_count, rng, positive_chosen);
  int count = 0;
  for (int chosen = 0; chosen < 2; ++chosen)
    for (int item = 0; item < 3; ++item)
      positions[count++] =
          orbit_members[negative_chosen[chosen]][item];
  for (int chosen = 0; chosen < 2; ++chosen)
    for (int item = 0; item < 3; ++item)
      positions[count++] =
          orbit_members[positive_chosen[chosen]][item];
  if (count != 12) {
    fprintf(stderr, "double triple swap has wrong support\n");
    exit(2);
  }
}

static void apply_double_id5_swap(state_t *state, int row,
                                  const int positions[12], int count,
                                  const int delta[HALF + 1],
                                  long long objective) {
  for (int item = 0; item < count; ++item)
    state->values[row][positions[item]] =
        -state->values[row][positions[item]];
  for (int shift = 1; shift <= HALF; ++shift) {
    state->paf[row][shift] += delta[shift];
    state->residual[shift] += delta[shift];
  }
  state->objective = objective;
}

static int double_id5_self_test(void) {
  rng_t rng = {UINT64_C(0x510e527fade682d1)};
  state_t state;
  initialize_id5_state(&state, &rng);
  for (int trial = 0; trial < 2000; ++trial) {
    int row = (int)(rng_next(&rng) % ROWS);
    int positions[12];
    int count;
    if (trial % 8 == 0) {
      choose_double_triple_swap(&state, row, &rng, positions);
      count = 12;
    } else {
      int single_positions[6];
      choose_orbit_swap(&state, row, &rng, single_positions, &count);
      memcpy(positions, single_positions,
             (size_t)count * sizeof(*positions));
    }
    int delta[HALF + 1];
    double_id5_multiflip_delta(state.values[row], positions, count,
                               delta);
    long long predicted = objective_after_delta(&state, delta);
    state_t direct = state;
    for (int item = 0; item < count; ++item)
      direct.values[row][positions[item]] =
          -direct.values[row][positions[item]];
    if (predicted != refresh_objective(&direct) ||
        !id5_invariance_and_sums_hold(&direct))
      return 0;
    apply_double_id5_swap(&state, row, positions, count, delta,
                          predicted);
  }
  state_t refreshed = state;
  return id5_invariance_and_sums_hold(&state) &&
         refresh_objective(&refreshed) == state.objective &&
         !memcmp(refreshed.residual, state.residual,
                 sizeof(state.residual));
}

static void emit_double_id5_progress(const search_record_t *record,
                                     double elapsed, uint64_t seed,
                                     uint64_t double_proposals) {
  printf("{\"elapsed_seconds\":%.1f,\"family_id\":5,\"seed\":%llu,"
         "\"proposals\":%llu,\"accepted\":%llu,\"restarts\":%llu,"
         "\"double_triple_proposals\":%llu,"
         "\"best_objective\":%lld,\"best_l1\":%lld,"
         "\"best_max_abs_residual\":%d}\n",
         elapsed, (unsigned long long)seed,
         (unsigned long long)record->iterations,
         (unsigned long long)record->accepted,
         (unsigned long long)record->restarts,
         (unsigned long long)double_proposals,
         record->best_objective, l1_residual(&record->best),
         record->best_max_abs_residual);
  fflush(stdout);
}

static void write_double_id5_result(
    const char *path, const search_record_t *record, uint64_t seed,
    double elapsed, double max_seconds,
    uint64_t proposals_per_restart, uint64_t double_proposals) {
  FILE *output = fopen(path, "w");
  if (!output) {
    fprintf(stderr, "failed to open '%s': %s\n", path, strerror(errno));
    exit(2);
  }
  fprintf(output,
          "{\n"
          "  \"schema\": "
          "\"frontiermath-lp333-id5-double-orbit-anneal-result-v1\",\n"
          "  \"status\": \"%s\",\n"
          "  \"family_id\": 5,\n"
          "  \"subgroup\": [1, 211, 232],\n"
          "  \"seed\": %llu,\n"
          "  \"elapsed_seconds\": %.9f,\n"
          "  \"max_seconds\": %.9f,\n"
          "  \"proposals_per_restart\": %llu,\n"
          "  \"iterations\": %llu,\n"
          "  \"accepted\": %llu,\n"
          "  \"improving\": %llu,\n"
          "  \"restarts\": %llu,\n"
          "  \"double_triple_proposals\": %llu,\n"
          "  \"incremental_self_test_trials\": 2000,\n"
          "  \"incremental_self_test\": \"PASS\",\n"
          "  \"best_objective\": %lld,\n"
          "  \"best_l1_residual\": %lld,\n"
          "  \"best_max_abs_residual\": %d,\n"
          "  \"a_sequence\": ",
          record->best_objective == 0 ? "candidate" : "nonterminal",
          (unsigned long long)seed, elapsed, max_seconds,
          (unsigned long long)proposals_per_restart,
          (unsigned long long)record->iterations,
          (unsigned long long)record->accepted,
          (unsigned long long)record->improving,
          (unsigned long long)record->restarts,
          (unsigned long long)double_proposals,
          record->best_objective, l1_residual(&record->best),
          record->best_max_abs_residual);
  write_array(output, record->best.values[0]);
  fprintf(output, ",\n  \"b_sequence\": ");
  write_array(output, record->best.values[1]);
  fprintf(output, ",\n  \"a_paf_independent\": ");
  write_int_array(output, record->best.paf[0]);
  fprintf(output, ",\n  \"b_paf_independent\": ");
  write_int_array(output, record->best.paf[1]);
  fprintf(output, ",\n  \"combined_residual_independent\": ");
  write_int_array(output, record->best.residual);
  fprintf(output, "\n}\n");
  if (fclose(output)) {
    perror("fclose");
    exit(2);
  }
}

static int run_double_id5_search(double max_seconds, uint64_t seed,
                                 const char *output_path,
                                 uint64_t proposals_per_restart) {
  if (!double_id5_self_test()) {
    fprintf(stderr, "double ID5 incremental self-test failed\n");
    return 2;
  }
  rng_t rng = {seed ? seed : UINT64_C(0x9e3779b97f4a7c15)};
  state_t current;
  initialize_id5_state(&current, &rng);
  search_record_t record;
  memset(&record, 0, sizeof(record));
  record.best = current;
  record.best_objective = current.objective;
  record.best_max_abs_residual = max_abs_residual(&current);

  const double started = monotonic_seconds();
  double next_progress = 60.0;
  uint64_t proposal_in_restart = 0;
  uint64_t double_proposals = 0;
  double temperature = 512.0;
  while (record.best_objective != 0) {
    if (!(record.iterations & UINT64_C(65535))) {
      double elapsed = monotonic_seconds() - started;
      if (elapsed >= max_seconds)
        break;
      if (elapsed >= next_progress) {
        emit_double_id5_progress(&record, elapsed, seed,
                                 double_proposals);
        next_progress += 60.0;
      }
    }
    if (proposal_in_restart >= proposals_per_restart) {
      initialize_id5_state(&current, &rng);
      ++record.restarts;
      proposal_in_restart = 0;
      temperature = 512.0;
    }
    if (!(proposal_in_restart & UINT64_C(4095))) {
      double fraction =
          (double)proposal_in_restart /
          (double)proposals_per_restart;
      temperature = 512.0 * pow(0.25 / 512.0, fraction);
    }
    int row = (int)(rng_next(&rng) % ROWS);
    int positions[12];
    int count;
    if (rng_next(&rng) % 8 == 0) {
      choose_double_triple_swap(&current, row, &rng, positions);
      count = 12;
      ++double_proposals;
    } else {
      int single_positions[6];
      choose_orbit_swap(&current, row, &rng, single_positions, &count);
      memcpy(positions, single_positions,
             (size_t)count * sizeof(*positions));
    }
    int delta[HALF + 1];
    double_id5_multiflip_delta(current.values[row], positions, count,
                               delta);
    long long proposed = objective_after_delta(&current, delta);
    long long increase = proposed - current.objective;
    int accept = increase <= 0;
    if (!accept) {
      double uniform =
          ((rng_next(&rng) >> 11) + 0.5) *
          (1.0 / 9007199254740992.0);
      accept = uniform < exp(-(double)increase / temperature);
    }
    ++record.iterations;
    ++proposal_in_restart;
    if (!accept)
      continue;
    if (proposed < current.objective)
      ++record.improving;
    ++record.accepted;
    apply_double_id5_swap(&current, row, positions, count, delta,
                          proposed);
    if (current.objective < record.best_objective) {
      record.best = current;
      record.best_objective = current.objective;
      record.best_max_abs_residual = max_abs_residual(&current);
    }
  }
  double elapsed = monotonic_seconds() - started;
  if (!id5_invariance_and_sums_hold(&record.best) ||
      refresh_objective(&record.best) != record.best_objective) {
    fprintf(stderr, "final double ID5 refresh failed\n");
    return 2;
  }
  emit_double_id5_progress(&record, elapsed, seed, double_proposals);
  write_double_id5_result(output_path, &record, seed, elapsed,
                          max_seconds, proposals_per_restart,
                          double_proposals);
  return 0;
}

int main(int argc, char **argv) {
  int self_test = 0;
  int initial = 0;
  double seconds = 0;
  uint64_t seed = 0;
  uint64_t proposals_per_restart = UINT64_C(2000000);
  const char *output = NULL;
  build_id5_orbits();
  for (int index = 1; index < argc; ++index) {
    if (!strcmp(argv[index], "--self-test")) {
      self_test = 1;
    } else if (!strcmp(argv[index], "--initial")) {
      initial = 1;
    } else if (!strcmp(argv[index], "--seconds") &&
               index + 1 < argc) {
      seconds = strtod(argv[++index], NULL);
    } else if (!strcmp(argv[index], "--seed") &&
               index + 1 < argc) {
      seed = strtoull(argv[++index], NULL, 10);
    } else if (!strcmp(argv[index], "--output") &&
               index + 1 < argc) {
      output = argv[++index];
    } else if (!strcmp(argv[index], "--proposals-per-restart") &&
               index + 1 < argc) {
      proposals_per_restart = strtoull(argv[++index], NULL, 10);
    } else {
      fprintf(stderr,
              "usage: %s --self-test | --initial --seed N | "
              "--seconds N --seed N --output PATH "
              "[--proposals-per-restart N]\n",
              argv[0]);
      return 2;
    }
  }
  if (self_test) {
    int pass = double_id5_self_test();
    printf("{\"family_id\":5,\"subgroup\":[1,211,232],"
           "\"double_triple_support\":12,"
           "\"incremental_self_test\":\"%s\",\"trials\":2000}\n",
           pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
  }
  if (initial) {
    if (!seed) {
      fprintf(stderr, "nonzero seed required\n");
      return 2;
    }
    rng_t rng = {seed};
    state_t state;
    initialize_id5_state(&state, &rng);
    printf("{\"family_id\":5,\"seed\":%llu,"
           "\"initial_objective\":%lld,\"initial_l1\":%lld,"
           "\"initial_max_abs_residual\":%d,\"invariance\":\"%s\"}\n",
           (unsigned long long)seed, state.objective,
           l1_residual(&state), max_abs_residual(&state),
           id5_invariance_and_sums_hold(&state) ? "PASS" : "FAIL");
    return id5_invariance_and_sums_hold(&state) ? 0 : 1;
  }
  if (!(seconds > 0) || !seed || !output ||
      !proposals_per_restart) {
    fprintf(stderr, "invalid or incomplete search arguments\n");
    return 2;
  }
  return run_double_id5_search(seconds, seed, output,
                               proposals_per_restart);
}
