/*
 * Add periodic six-coordinate proposals to the exact pq2 annealer.
 *
 * The included baseline supplies the audited exact PAF delta, margin,
 * serialization, and RNG machinery.  Renaming its entry point keeps this
 * file a separate, hashable intervention without changing the active
 * baseline source.
 */
#define main lp333_pq2_baseline_main
#include "search_lp333_pq2_anneal.c"
#undef main

static int apply_random_swap_to_copy(state_t *state, rng_t *rng) {
  int row = (int)(rng_next(rng) % ROWS);
  int left, right;
  int delta[HALF + 1];
  choose_swap(state, row, rng, &left, &right);
  swap_paf_delta(state->values[row], left, right, delta);
  long long objective = objective_after_delta(state, delta);
  apply_swap(state, row, left, right, delta, objective);
  return row;
}

static int six_coordinate_self_test(void) {
  rng_t rng = {UINT64_C(0xbb67ae8584caa73b)};
  state_t state;
  initialize_state(&state, &rng);
  for (int trial = 1; trial <= 2000; ++trial) {
    state_t proposed = state;
    int swaps = trial % 8 == 0 ? 3 : 1;
    for (int item = 0; item < swaps; ++item)
      apply_random_swap_to_copy(&proposed, &rng);
    state_t direct = proposed;
    long long direct_objective = refresh_objective(&direct);
    if (direct_objective != proposed.objective)
      return 0;
    if (memcmp(direct.paf, proposed.paf, sizeof(proposed.paf)))
      return 0;
    if (memcmp(direct.residual, proposed.residual,
               sizeof(proposed.residual)))
      return 0;
    if (!exact_margins_hold(&proposed))
      return 0;
    state = proposed;
  }
  return 1;
}

static void emit_six_coordinate_progress(const search_record_t *record,
                                         double elapsed, uint64_t seed,
                                         uint64_t triple_proposals) {
  printf("{\"elapsed_seconds\":%.1f,\"seed\":%llu,"
         "\"proposals\":%llu,\"accepted\":%llu,\"restarts\":%llu,"
         "\"triple_swap_proposals\":%llu,"
         "\"best_objective\":%lld,\"best_l1\":%lld,"
         "\"best_max_abs_residual\":%d}\n",
         elapsed, (unsigned long long)seed,
         (unsigned long long)record->iterations,
         (unsigned long long)record->accepted,
         (unsigned long long)record->restarts,
         (unsigned long long)triple_proposals, record->best_objective,
         l1_residual(&record->best), record->best_max_abs_residual);
  fflush(stdout);
}

static void write_mechanism_result(const char *result_path,
                                   const search_record_t *record,
                                   uint64_t triple_proposals) {
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
          "\"frontiermath-lp333-pq2-six-coordinate-mechanism-v1\",\n"
          "  \"single_swap_proposals\": %llu,\n"
          "  \"triple_swap_proposals\": %llu,\n"
          "  \"total_proposals\": %llu,\n"
          "  \"triple_proposal_period\": 8,\n"
          "  \"triple_proposal_coordinates\": 6,\n"
          "  \"self_test_mixed_proposals\": 2000,\n"
          "  \"self_test\": \"PASS\"\n"
          "}\n",
          (unsigned long long)(record->iterations - triple_proposals),
          (unsigned long long)triple_proposals,
          (unsigned long long)record->iterations);
  if (fclose(output)) {
    perror("fclose");
    exit(2);
  }
}

static int run_six_coordinate_search(double max_seconds, uint64_t seed,
                                     const char *output_path,
                                     uint64_t proposals_per_restart) {
  if (!incremental_self_test() || !six_coordinate_self_test()) {
    fprintf(stderr, "incremental or six-coordinate self-test failed\n");
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

  const double started = monotonic_seconds();
  double next_progress = 60.0;
  uint64_t proposal_in_restart = 0;
  uint64_t triple_proposals = 0;
  double temperature = 512.0;
  while (record.best_objective != 0) {
    if (!(record.iterations & UINT64_C(65535))) {
      double elapsed = monotonic_seconds() - started;
      if (elapsed >= max_seconds)
        break;
      if (elapsed >= next_progress) {
        emit_six_coordinate_progress(&record, elapsed, seed,
                                     triple_proposals);
        next_progress += 60.0;
      }
    }
    if (proposal_in_restart >= proposals_per_restart) {
      initialize_state(&current, &rng);
      ++record.restarts;
      proposal_in_restart = 0;
      temperature = 512.0;
    }
    if (!(proposal_in_restart & UINT64_C(4095))) {
      double fraction =
          (double)proposal_in_restart / (double)proposals_per_restart;
      temperature = 512.0 * pow(0.25 / 512.0, fraction);
    }

    int triple = (record.iterations + 1) % 8 == 0;
    long long proposed_objective;
    state_t triple_state;
    int row = 0;
    int left = 0;
    int right = 0;
    int delta[HALF + 1] = {0};
    if (triple) {
      triple_state = current;
      for (int item = 0; item < 3; ++item)
        apply_random_swap_to_copy(&triple_state, &rng);
      proposed_objective = triple_state.objective;
      ++triple_proposals;
    } else {
      row = (int)(rng_next(&rng) % ROWS);
      choose_swap(&current, row, &rng, &left, &right);
      swap_paf_delta(current.values[row], left, right, delta);
      proposed_objective = objective_after_delta(&current, delta);
    }
    long long increase = proposed_objective - current.objective;
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
    if (proposed_objective < current.objective)
      ++record.improving;
    ++record.accepted;
    if (triple)
      current = triple_state;
    else
      apply_swap(&current, row, left, right, delta, proposed_objective);
    if (current.objective < record.best_objective) {
      record.best = current;
      record.best_objective = current.objective;
      record.best_max_abs_residual = max_abs_residual(&current);
    }
  }
  double elapsed = monotonic_seconds() - started;
  if (!exact_margins_hold(&record.best) ||
      refresh_objective(&record.best) != record.best_objective) {
    fprintf(stderr, "final direct refresh or margin check failed\n");
    return 2;
  }
  emit_six_coordinate_progress(&record, elapsed, seed, triple_proposals);
  write_result(output_path, &record, seed, elapsed, max_seconds,
               proposals_per_restart);
  write_mechanism_result(output_path, &record, triple_proposals);
  return 0;
}

int main(int argc, char **argv) {
  int self_test = 0;
  int initial = 0;
  double seconds = 0;
  uint64_t seed = 0;
  uint64_t proposals_per_restart = UINT64_C(2000000);
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
    int baseline = incremental_self_test();
    int mixed = six_coordinate_self_test();
    printf("{\"baseline_incremental\":\"%s\","
           "\"six_coordinate_incremental\":\"%s\","
           "\"mixed_trials\":2000}\n",
           baseline ? "PASS" : "FAIL", mixed ? "PASS" : "FAIL");
    return baseline && mixed ? 0 : 1;
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
  if (!(seconds > 0) || !seed || !output ||
      !proposals_per_restart) {
    fprintf(stderr, "invalid or incomplete search arguments\n");
    return 2;
  }
  return run_six_coordinate_search(seconds, seed, output,
                                   proposals_per_restart);
}
