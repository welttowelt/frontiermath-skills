/*
 * Full-neighborhood tabu search for the correct p=37, q=3 prescribed slice.
 *
 * The included baseline supplies the exact source-correct margins, PAF delta,
 * objective, deterministic RNG, result serializer, and independent refresh
 * checks.  This intervention enumerates every legal opposite-sign swap at
 * each step, chooses the best non-tabu neighbor (with global-best
 * aspiration), and takes it even when it is uphill.
 */
#define main lp333_pq2_baseline_main
#include "search_lp333_pq2_anneal.c"
#undef main

enum {
  TABU_TENURE_MIN = 7,
  TABU_TENURE_SPAN = 8,
  STAGNATION_RESTART_SWEEPS = 20000
};

static int tabu_self_test(void) {
  rng_t rng = {UINT64_C(0x3c6ef372fe94f82b)};
  state_t state;
  initialize_state(&state, &rng);
  int counted = 0;
  for (int row = 0; row < ROWS; ++row)
    for (int residue = 0; residue < CLASSES; ++residue)
      for (int left = residue; left < LENGTH; left += CLASSES)
        for (int right = left + CLASSES; right < LENGTH;
             right += CLASSES)
          if (state.values[row][left] != state.values[row][right]) {
            int delta[HALF + 1];
            swap_paf_delta(state.values[row], left, right, delta);
            long long predicted = objective_after_delta(&state, delta);
            state_t direct = state;
            direct.values[row][left] = -direct.values[row][left];
            direct.values[row][right] = -direct.values[row][right];
            if (predicted != refresh_objective(&direct))
              return 0;
            ++counted;
          }
  return counted == 1336 && exact_margins_hold(&state);
}

static void emit_tabu_progress(const search_record_t *record, double elapsed,
                               uint64_t seed, uint64_t uphill_moves) {
  printf("{\"elapsed_seconds\":%.1f,\"seed\":%llu,"
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

static void write_tabu_mechanism(const char *result_path,
                                 const search_record_t *record,
                                 uint64_t uphill_moves) {
  char path[4096];
  int rendered = snprintf(path, sizeof(path), "%s.mechanism.json", result_path);
  if (rendered < 0 || (size_t)rendered >= sizeof(path)) {
    fprintf(stderr, "mechanism-result path is too long\n");
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
          "\"frontiermath-lp333-pq2-full-neighborhood-tabu-v1\",\n"
          "  \"legal_neighbors_per_state\": 1336,\n"
          "  \"full_neighborhood_sweeps\": %llu,\n"
          "  \"applied_moves\": %llu,\n"
          "  \"uphill_moves\": %llu,\n"
          "  \"tabu_tenure_min\": %d,\n"
          "  \"tabu_tenure_max\": %d,\n"
          "  \"stagnation_restart_sweeps\": %d,\n"
          "  \"full_neighborhood_self_test\": \"PASS\"\n"
          "}\n",
          (unsigned long long)record->iterations,
          (unsigned long long)record->accepted,
          (unsigned long long)uphill_moves, TABU_TENURE_MIN,
          TABU_TENURE_MIN + TABU_TENURE_SPAN - 1,
          STAGNATION_RESTART_SWEEPS);
  if (fclose(output)) {
    perror("fclose");
    exit(2);
  }
}

static int run_tabu_search(double max_seconds, uint64_t seed,
                           const char *output_path) {
  if (!incremental_self_test() || !tabu_self_test()) {
    fprintf(stderr, "baseline or tabu self-test failed\n");
    return 2;
  }
  rng_t rng = {seed ? seed : UINT64_C(0x9e3779b97f4a7c15)};
  state_t current;
  initialize_state(&current, &rng);
  search_record_t record;
  memset(&record, 0, sizeof(record));
  record.best = current;
  record.best_objective = current.objective;
  record.best_max_abs_residual = max_abs_residual(&current);

  uint64_t tabu_until[ROWS][LENGTH];
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
      emit_tabu_progress(&record, elapsed, seed, uphill_moves);
      next_progress += 60.0;
    }
    if (record.iterations - last_global_improvement >=
        STAGNATION_RESTART_SWEEPS) {
      initialize_state(&current, &rng);
      memset(tabu_until, 0, sizeof(tabu_until));
      ++record.restarts;
      last_global_improvement = record.iterations;
    }

    int best_row = -1;
    int best_left = -1;
    int best_right = -1;
    int best_delta[HALF + 1] = {0};
    long long best_neighbor_objective = 0;
    uint64_t tied_best = 0;
    for (int row = 0; row < ROWS; ++row)
      for (int residue = 0; residue < CLASSES; ++residue)
        for (int left = residue; left < LENGTH; left += CLASSES)
          for (int right = left + CLASSES; right < LENGTH;
               right += CLASSES) {
            if (current.values[row][left] ==
                current.values[row][right])
              continue;
            int delta[HALF + 1];
            swap_paf_delta(current.values[row], left, right, delta);
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
              memcpy(best_delta, delta, sizeof(best_delta));
              best_neighbor_objective = proposed;
              tied_best = 1;
            } else if (proposed == best_neighbor_objective) {
              ++tied_best;
              if (rng_next(&rng) % tied_best == 0) {
                best_row = row;
                best_left = left;
                best_right = right;
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
    apply_swap(&current, best_row, best_left, best_right, best_delta,
               best_neighbor_objective);
    ++record.iterations;
    ++record.accepted;
    uint64_t tenure =
        TABU_TENURE_MIN + rng_next(&rng) % TABU_TENURE_SPAN;
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
  if (!exact_margins_hold(&record.best) ||
      refresh_objective(&record.best) != record.best_objective) {
    fprintf(stderr, "final direct refresh or margin check failed\n");
    return 2;
  }
  emit_tabu_progress(&record, elapsed, seed, uphill_moves);
  write_result(output_path, &record, seed, elapsed, max_seconds,
               STAGNATION_RESTART_SWEEPS);
  write_tabu_mechanism(output_path, &record, uphill_moves);
  return 0;
}

int main(int argc, char **argv) {
  int self_test = 0;
  int initial = 0;
  double seconds = 0;
  uint64_t seed = 0;
  const char *output = NULL;
  for (int index = 1; index < argc; ++index) {
    if (!strcmp(argv[index], "--self-test")) {
      self_test = 1;
    } else if (!strcmp(argv[index], "--initial")) {
      initial = 1;
    } else if (!strcmp(argv[index], "--seconds") && index + 1 < argc) {
      seconds = strtod(argv[++index], NULL);
    } else if (!strcmp(argv[index], "--seed") && index + 1 < argc) {
      seed = strtoull(argv[++index], NULL, 10);
    } else if (!strcmp(argv[index], "--output") && index + 1 < argc) {
      output = argv[++index];
    } else {
      fprintf(stderr,
              "usage: %s --self-test | --initial --seed N | "
              "--seconds N --seed N --output PATH\n",
              argv[0]);
      return 2;
    }
  }
  if (self_test) {
    int baseline = incremental_self_test();
    int tabu = tabu_self_test();
    printf("{\"baseline_incremental\":\"%s\","
           "\"full_neighborhood_tabu\":\"%s\","
           "\"legal_neighbors\":1336}\n",
           baseline ? "PASS" : "FAIL", tabu ? "PASS" : "FAIL");
    return baseline && tabu ? 0 : 1;
  }
  if (initial) {
    if (!seed) {
      fprintf(stderr, "nonzero seed required\n");
      return 2;
    }
    rng_t rng = {seed};
    state_t state;
    initialize_state(&state, &rng);
    printf("{\"seed\":%llu,\"initial_objective\":%lld,"
           "\"initial_l1\":%lld,\"initial_max_abs_residual\":%d,"
           "\"margins\":\"%s\"}\n",
           (unsigned long long)seed, state.objective,
           l1_residual(&state), max_abs_residual(&state),
           exact_margins_hold(&state) ? "PASS" : "FAIL");
    return exact_margins_hold(&state) ? 0 : 1;
  }
  if (!(seconds > 0) || !seed || !output) {
    fprintf(stderr, "invalid or incomplete search arguments\n");
    return 2;
  }
  return run_tabu_search(seconds, seed, output);
}
