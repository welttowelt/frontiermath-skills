/*
 * Full-neighborhood tabu search inside LP333 fixed family ID5.
 *
 * The exact state space has three singleton and 110 triple multiplication
 * orbits under H={1,211,232}.  Each row has one negative singleton and 55
 * negative triples.  A legal move exchanges the signs of two equal-size
 * opposite-sign orbits.  At every sweep this program evaluates all 6054
 * legal moves across both rows, applies the best admissible move, and uses
 * global-best aspiration plus deterministic tabu tenure.
 */
#include <ctype.h>

#define main lp333_pq2_baseline_main
#include "search_lp333_pq2_anneal.c"
#undef main

enum {
  ID5_TABU_ORBITS = 113,
  ID5_TABU_GENERATOR = 211,
  ID5_TABU_TENURE_MIN = 7,
  ID5_TABU_TENURE_SPAN = 8,
  ID5_TABU_STAGNATION_SWEEPS = 5000,
  ID5_TABU_PERTURBATION_MOVES = 64,
  ID5_TABU_NEIGHBORS = 6054
};

static int id5_tabu_orbit_count;
static int id5_tabu_orbit_size[ID5_TABU_ORBITS];
static int id5_tabu_orbit_members[ID5_TABU_ORBITS][3];
static int id5_tabu_coordinate_orbit[LENGTH];

static void id5_tabu_build_orbits(void) {
  for (int index = 0; index < LENGTH; ++index)
    id5_tabu_coordinate_orbit[index] = -1;
  id5_tabu_orbit_count = 0;
  for (int seed = 0; seed < LENGTH; ++seed) {
    if (id5_tabu_coordinate_orbit[seed] >= 0)
      continue;
    int value = seed;
    int size = 0;
    do {
      if (size >= 3) {
        fprintf(stderr, "ID5 orbit exceeded order three\n");
        exit(2);
      }
      id5_tabu_orbit_members[id5_tabu_orbit_count][size++] = value;
      id5_tabu_coordinate_orbit[value] = id5_tabu_orbit_count;
      value = (value * ID5_TABU_GENERATOR) % LENGTH;
    } while (value != seed);
    id5_tabu_orbit_size[id5_tabu_orbit_count++] = size;
  }
  int singletons = 0;
  int triples = 0;
  for (int orbit = 0; orbit < id5_tabu_orbit_count; ++orbit) {
    singletons += id5_tabu_orbit_size[orbit] == 1;
    triples += id5_tabu_orbit_size[orbit] == 3;
  }
  if (id5_tabu_orbit_count != ID5_TABU_ORBITS ||
      singletons != 3 || triples != 110) {
    fprintf(stderr, "ID5 orbit signature changed\n");
    exit(2);
  }
}

static int id5_tabu_row_sum(const int8_t row[LENGTH]) {
  int result = 0;
  for (int index = 0; index < LENGTH; ++index)
    result += row[index];
  return result;
}

static int id5_tabu_invariants_hold(const state_t *state) {
  for (int row = 0; row < ROWS; ++row) {
    if (id5_tabu_row_sum(state->values[row]) != 1)
      return 0;
    int negative_singletons = 0;
    int negative_triples = 0;
    for (int orbit = 0; orbit < id5_tabu_orbit_count; ++orbit) {
      int8_t sign =
          state->values[row][id5_tabu_orbit_members[orbit][0]];
      for (int item = 1; item < id5_tabu_orbit_size[orbit]; ++item)
        if (state->values[row][id5_tabu_orbit_members[orbit][item]] !=
            sign)
          return 0;
      if (sign < 0) {
        negative_singletons += id5_tabu_orbit_size[orbit] == 1;
        negative_triples += id5_tabu_orbit_size[orbit] == 3;
      }
    }
    if (negative_singletons != 1 || negative_triples != 55)
      return 0;
  }
  return 1;
}

static void id5_tabu_initialize_row(int8_t row[LENGTH], rng_t *rng) {
  int singleton_ids[3];
  int triple_ids[110];
  int singletons = 0;
  int triples = 0;
  for (int orbit = 0; orbit < id5_tabu_orbit_count; ++orbit) {
    if (id5_tabu_orbit_size[orbit] == 1)
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
  for (int orbit = 0; orbit < id5_tabu_orbit_count; ++orbit) {
    int8_t sign = orbit == negative_singleton ? -1 : 1;
    for (int item = 0; item < 55; ++item)
      if (orbit == triple_ids[item])
        sign = -1;
    for (int item = 0; item < id5_tabu_orbit_size[orbit]; ++item)
      row[id5_tabu_orbit_members[orbit][item]] = sign;
  }
}

static void id5_tabu_initialize_state(state_t *state, rng_t *rng) {
  id5_tabu_initialize_row(state->values[0], rng);
  id5_tabu_initialize_row(state->values[1], rng);
  refresh_objective(state);
}

static int id5_tabu_flipped_index(int index, const int positions[6],
                                  int count) {
  for (int item = 0; item < count; ++item)
    if (positions[item] == index)
      return 1;
  return 0;
}

static int id5_tabu_value_after_many(const int8_t row[LENGTH], int index,
                                     const int positions[6], int count) {
  int value = row[index];
  return id5_tabu_flipped_index(index, positions, count) ? -value : value;
}

static void id5_tabu_multiflip_delta(const int8_t row[LENGTH],
                                     const int positions[6], int count,
                                     int delta[HALF + 1]) {
  delta[0] = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    int starts[12];
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
          id5_tabu_value_after_many(row, start, positions, count) *
          id5_tabu_value_after_many(row, end, positions, count);
      change += new_product - old_product;
    }
    delta[shift] = change;
  }
}

static int id5_tabu_positions_for_orbits(int left, int right,
                                         int positions[6]) {
  int count = 0;
  for (int item = 0; item < id5_tabu_orbit_size[left]; ++item)
    positions[count++] = id5_tabu_orbit_members[left][item];
  for (int item = 0; item < id5_tabu_orbit_size[right]; ++item)
    positions[count++] = id5_tabu_orbit_members[right][item];
  return count;
}

static void id5_tabu_apply(state_t *state, int row,
                           const int positions[6], int count,
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

static void id5_tabu_choose_random_swap(const state_t *state, int row,
                                        rng_t *rng, int *left,
                                        int *right) {
  int size = rng_next(rng) % 8 == 0 ? 1 : 3;
  int negative[110];
  int positive[110];
  int negative_count = 0;
  int positive_count = 0;
  for (int orbit = 0; orbit < id5_tabu_orbit_count; ++orbit) {
    if (id5_tabu_orbit_size[orbit] != size)
      continue;
    int sign =
        state->values[row][id5_tabu_orbit_members[orbit][0]];
    if (sign < 0)
      negative[negative_count++] = orbit;
    else
      positive[positive_count++] = orbit;
  }
  *left = negative[rng_next(rng) % (uint64_t)negative_count];
  *right = positive[rng_next(rng) % (uint64_t)positive_count];
}

static int id5_tabu_parse_sequence(const char *text, const char *label,
                                   int8_t row[LENGTH]) {
  const char *cursor = strstr(text, label);
  if (!cursor)
    return 0;
  cursor = strchr(cursor, '[');
  if (!cursor)
    return 0;
  ++cursor;
  for (int index = 0; index < LENGTH; ++index) {
    while (*cursor && isspace((unsigned char)*cursor))
      ++cursor;
    char *end = NULL;
    long value = strtol(cursor, &end, 10);
    if (end == cursor || (value != -1 && value != 1))
      return 0;
    row[index] = (int8_t)value;
    cursor = end;
    while (*cursor && isspace((unsigned char)*cursor))
      ++cursor;
    if (index + 1 < LENGTH) {
      if (*cursor != ',')
        return 0;
      ++cursor;
    }
  }
  return 1;
}

static int id5_tabu_load_start(const char *path, state_t *state) {
  FILE *input = fopen(path, "rb");
  if (!input) {
    fprintf(stderr, "failed to open start '%s': %s\n", path,
            strerror(errno));
    return 0;
  }
  if (fseek(input, 0, SEEK_END)) {
    fclose(input);
    return 0;
  }
  long size = ftell(input);
  if (size < 0 || size > 16 * 1024 * 1024 || fseek(input, 0, SEEK_SET)) {
    fclose(input);
    return 0;
  }
  char *text = malloc((size_t)size + 1);
  if (!text) {
    fclose(input);
    return 0;
  }
  size_t read_size = fread(text, 1, (size_t)size, input);
  int close_status = fclose(input);
  text[read_size] = '\0';
  int parsed =
      read_size == (size_t)size && close_status == 0 &&
      id5_tabu_parse_sequence(text, "\"a_sequence\"",
                              state->values[0]) &&
      id5_tabu_parse_sequence(text, "\"b_sequence\"",
                              state->values[1]);
  free(text);
  if (!parsed)
    return 0;
  refresh_objective(state);
  return id5_tabu_invariants_hold(state);
}

static int id5_tabu_full_neighborhood_self_test(void) {
  rng_t rng = {UINT64_C(0xbb67ae8584caa73b)};
  state_t state;
  id5_tabu_initialize_state(&state, &rng);
  int counted = 0;
  for (int row = 0; row < ROWS; ++row)
    for (int left = 0; left < id5_tabu_orbit_count; ++left)
      for (int right = left + 1; right < id5_tabu_orbit_count;
           ++right) {
        if (id5_tabu_orbit_size[left] !=
                id5_tabu_orbit_size[right] ||
            state.values[row][id5_tabu_orbit_members[left][0]] ==
                state.values[row][id5_tabu_orbit_members[right][0]])
          continue;
        int positions[6];
        int count =
            id5_tabu_positions_for_orbits(left, right, positions);
        int delta[HALF + 1];
        id5_tabu_multiflip_delta(state.values[row], positions, count,
                                 delta);
        long long predicted = objective_after_delta(&state, delta);
        state_t direct = state;
        for (int item = 0; item < count; ++item)
          direct.values[row][positions[item]] =
              -direct.values[row][positions[item]];
        if (predicted != refresh_objective(&direct) ||
            !id5_tabu_invariants_hold(&direct))
          return 0;
        ++counted;
      }
  return counted == ID5_TABU_NEIGHBORS &&
         id5_tabu_invariants_hold(&state);
}

static void id5_tabu_perturb_from_best(state_t *current,
                                       const state_t *best, rng_t *rng) {
  *current = *best;
  for (int move = 0; move < ID5_TABU_PERTURBATION_MOVES; ++move) {
    int row = (int)(rng_next(rng) % ROWS);
    int left;
    int right;
    id5_tabu_choose_random_swap(current, row, rng, &left, &right);
    int positions[6];
    int count = id5_tabu_positions_for_orbits(left, right, positions);
    int delta[HALF + 1];
    id5_tabu_multiflip_delta(current->values[row], positions, count,
                             delta);
    long long proposed = objective_after_delta(current, delta);
    id5_tabu_apply(current, row, positions, count, delta, proposed);
  }
}

static void id5_tabu_emit_progress(const search_record_t *record,
                                   double elapsed, uint64_t seed,
                                   uint64_t uphill_moves) {
  printf("{\"elapsed_seconds\":%.1f,\"family_id\":5,\"seed\":%llu,"
         "\"full_neighborhood_sweeps\":%llu,\"moves\":%llu,"
         "\"uphill_moves\":%llu,\"restarts\":%llu,"
         "\"best_objective\":%lld,\"best_l1\":%lld,"
         "\"best_max_abs_residual\":%d}\n",
         elapsed, (unsigned long long)seed,
         (unsigned long long)record->iterations,
         (unsigned long long)record->accepted,
         (unsigned long long)uphill_moves,
         (unsigned long long)record->restarts, record->best_objective,
         l1_residual(&record->best), record->best_max_abs_residual);
  fflush(stdout);
}

static void id5_tabu_write_result(const char *path,
                                  const search_record_t *record,
                                  uint64_t seed, double elapsed,
                                  double max_seconds) {
  FILE *output = fopen(path, "w");
  if (!output) {
    fprintf(stderr, "failed to open '%s': %s\n", path, strerror(errno));
    exit(2);
  }
  fprintf(output,
          "{\n"
          "  \"schema\": "
          "\"frontiermath-lp333-id5-orbit-tabu-result-v1\",\n"
          "  \"status\": \"%s\",\n"
          "  \"family_id\": 5,\n"
          "  \"subgroup\": [1, 211, 232],\n"
          "  \"seed\": %llu,\n"
          "  \"elapsed_seconds\": %.9f,\n"
          "  \"max_seconds\": %.9f,\n"
          "  \"iterations\": %llu,\n"
          "  \"accepted\": %llu,\n"
          "  \"improving\": %llu,\n"
          "  \"restarts\": %llu,\n"
          "  \"best_objective\": %lld,\n"
          "  \"best_l1_residual\": %lld,\n"
          "  \"best_max_abs_residual\": %d,\n"
          "  \"a_sequence\": ",
          record->best_objective == 0 ? "candidate" : "nonterminal",
          (unsigned long long)seed, elapsed, max_seconds,
          (unsigned long long)record->iterations,
          (unsigned long long)record->accepted,
          (unsigned long long)record->improving,
          (unsigned long long)record->restarts, record->best_objective,
          l1_residual(&record->best), record->best_max_abs_residual);
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

static void id5_tabu_write_mechanism(const char *result_path,
                                     const search_record_t *record,
                                     uint64_t uphill_moves,
                                     const char *start_path,
                                     long long start_objective) {
  char path[4096];
  int rendered =
      snprintf(path, sizeof(path), "%s.mechanism.json", result_path);
  if (rendered < 0 || (size_t)rendered >= sizeof(path)) {
    fprintf(stderr, "mechanism path is too long\n");
    exit(2);
  }
  FILE *output = fopen(path, "w");
  if (!output) {
    fprintf(stderr, "failed to open '%s': %s\n", path, strerror(errno));
    exit(2);
  }
  fprintf(output,
          "{\n"
          "  \"schema\": "
          "\"frontiermath-lp333-id5-full-neighborhood-tabu-v1\",\n"
          "  \"start_path\": \"%s\",\n"
          "  \"start_objective\": %lld,\n"
          "  \"legal_neighbors_per_state\": %d,\n"
          "  \"full_neighborhood_sweeps\": %llu,\n"
          "  \"applied_moves\": %llu,\n"
          "  \"uphill_moves\": %llu,\n"
          "  \"tabu_tenure_min\": %d,\n"
          "  \"tabu_tenure_max\": %d,\n"
          "  \"stagnation_restart_sweeps\": %d,\n"
          "  \"perturbation_moves\": %d,\n"
          "  \"full_neighborhood_self_test\": \"PASS\"\n"
          "}\n",
          start_path, start_objective, ID5_TABU_NEIGHBORS,
          (unsigned long long)record->iterations,
          (unsigned long long)record->accepted,
          (unsigned long long)uphill_moves, ID5_TABU_TENURE_MIN,
          ID5_TABU_TENURE_MIN + ID5_TABU_TENURE_SPAN - 1,
          ID5_TABU_STAGNATION_SWEEPS, ID5_TABU_PERTURBATION_MOVES);
  if (fclose(output)) {
    perror("fclose");
    exit(2);
  }
}

static int id5_tabu_run(double max_seconds, uint64_t seed,
                        const char *start_path,
                        const char *output_path) {
  if (!id5_tabu_full_neighborhood_self_test()) {
    fprintf(stderr, "ID5 full-neighborhood self-test failed\n");
    return 2;
  }
  state_t current;
  if (!id5_tabu_load_start(start_path, &current)) {
    fprintf(stderr, "invalid ID5 start state\n");
    return 2;
  }
  long long start_objective = current.objective;
  rng_t rng = {seed ? seed : UINT64_C(0x9e3779b97f4a7c15)};
  search_record_t record;
  memset(&record, 0, sizeof(record));
  record.best = current;
  record.best_objective = current.objective;
  record.best_max_abs_residual = max_abs_residual(&current);

  uint64_t tabu_until[ROWS][ID5_TABU_ORBITS];
  memset(tabu_until, 0, sizeof(tabu_until));
  uint64_t last_global_improvement = 0;
  uint64_t uphill_moves = 0;
  const double started = monotonic_seconds();
  double next_progress = 60.0;

  while (record.best_objective != 0) {
    double elapsed = monotonic_seconds() - started;
    if (elapsed >= max_seconds)
      break;
    if (elapsed >= next_progress) {
      id5_tabu_emit_progress(&record, elapsed, seed, uphill_moves);
      next_progress += 60.0;
    }
    if (record.iterations - last_global_improvement >=
        ID5_TABU_STAGNATION_SWEEPS) {
      id5_tabu_perturb_from_best(&current, &record.best, &rng);
      memset(tabu_until, 0, sizeof(tabu_until));
      ++record.restarts;
      last_global_improvement = record.iterations;
    }

    int best_row = -1;
    int best_left = -1;
    int best_right = -1;
    int best_count = 0;
    int best_positions[6] = {0};
    int best_delta[HALF + 1] = {0};
    long long best_neighbor_objective = 0;
    uint64_t tied_best = 0;
    for (int row = 0; row < ROWS; ++row)
      for (int left = 0; left < id5_tabu_orbit_count; ++left)
        for (int right = left + 1; right < id5_tabu_orbit_count;
             ++right) {
          if (id5_tabu_orbit_size[left] !=
                  id5_tabu_orbit_size[right] ||
              current.values[row]
                            [id5_tabu_orbit_members[left][0]] ==
                  current.values[row]
                                [id5_tabu_orbit_members[right][0]])
            continue;
          int positions[6];
          int count =
              id5_tabu_positions_for_orbits(left, right, positions);
          int delta[HALF + 1];
          id5_tabu_multiflip_delta(current.values[row], positions,
                                   count, delta);
          long long proposed = objective_after_delta(&current, delta);
          int tabu =
              tabu_until[row][left] > record.iterations ||
              tabu_until[row][right] > record.iterations;
          if (tabu && proposed >= record.best_objective)
            continue;
          if (best_row < 0 || proposed < best_neighbor_objective) {
            best_row = row;
            best_left = left;
            best_right = right;
            best_count = count;
            memcpy(best_positions, positions, sizeof(best_positions));
            memcpy(best_delta, delta, sizeof(best_delta));
            best_neighbor_objective = proposed;
            tied_best = 1;
          } else if (proposed == best_neighbor_objective) {
            ++tied_best;
            if (rng_next(&rng) % tied_best == 0) {
              best_row = row;
              best_left = left;
              best_right = right;
              best_count = count;
              memcpy(best_positions, positions,
                     sizeof(best_positions));
              memcpy(best_delta, delta, sizeof(best_delta));
            }
          }
        }
    if (best_row < 0) {
      fprintf(stderr, "tabu tenure excluded every legal neighbor\n");
      return 2;
    }
    if (best_neighbor_objective > current.objective)
      ++uphill_moves;
    if (best_neighbor_objective < current.objective)
      ++record.improving;
    id5_tabu_apply(&current, best_row, best_positions, best_count,
                   best_delta, best_neighbor_objective);
    ++record.iterations;
    ++record.accepted;
    uint64_t tenure =
        ID5_TABU_TENURE_MIN + rng_next(&rng) % ID5_TABU_TENURE_SPAN;
    tabu_until[best_row][best_left] = record.iterations + tenure;
    tabu_until[best_row][best_right] = record.iterations + tenure;
    if (current.objective < record.best_objective) {
      record.best = current;
      record.best_objective = current.objective;
      record.best_max_abs_residual = max_abs_residual(&current);
      last_global_improvement = record.iterations;
    }
  }

  double elapsed = monotonic_seconds() - started;
  if (!id5_tabu_invariants_hold(&record.best) ||
      refresh_objective(&record.best) != record.best_objective) {
    fprintf(stderr, "final ID5 refresh or invariance check failed\n");
    return 2;
  }
  id5_tabu_emit_progress(&record, elapsed, seed, uphill_moves);
  id5_tabu_write_result(output_path, &record, seed, elapsed,
                        max_seconds);
  id5_tabu_write_mechanism(output_path, &record, uphill_moves,
                           start_path, start_objective);
  return 0;
}

int main(int argc, char **argv) {
  int self_test = 0;
  double seconds = 0;
  uint64_t seed = 0;
  const char *start = NULL;
  const char *output = NULL;
  id5_tabu_build_orbits();
  for (int index = 1; index < argc; ++index) {
    if (!strcmp(argv[index], "--self-test")) {
      self_test = 1;
    } else if (!strcmp(argv[index], "--seconds") &&
               index + 1 < argc) {
      seconds = strtod(argv[++index], NULL);
    } else if (!strcmp(argv[index], "--seed") &&
               index + 1 < argc) {
      seed = strtoull(argv[++index], NULL, 10);
    } else if (!strcmp(argv[index], "--start") &&
               index + 1 < argc) {
      start = argv[++index];
    } else if (!strcmp(argv[index], "--output") &&
               index + 1 < argc) {
      output = argv[++index];
    } else {
      fprintf(stderr,
              "usage: %s --self-test | --seconds N --seed N "
              "--start PATH --output PATH\n",
              argv[0]);
      return 2;
    }
  }
  if (self_test) {
    int pass = id5_tabu_full_neighborhood_self_test();
    printf("{\"family_id\":5,\"subgroup\":[1,211,232],"
           "\"legal_neighbors\":%d,"
           "\"full_neighborhood_self_test\":\"%s\"}\n",
           ID5_TABU_NEIGHBORS, pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
  }
  if (!(seconds > 0) || !seed || !start || !output) {
    fprintf(stderr, "invalid or incomplete search arguments\n");
    return 2;
  }
  return id5_tabu_run(seconds, seed, start, output);
}
