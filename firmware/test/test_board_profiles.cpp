#include <cstdio>
#include <cstring>

#include "BoardProfile.h"

int runBoardProfileTests() {
    int passed = 0;
    int failed = 0;
    auto check = [&](bool condition, const char* description) {
        if (condition) ++passed;
        else {
            std::printf("    FAIL: test_board_profiles: %s\n", description);
            ++failed;
        }
    };

    const auto& a8 = board::GetBoardProfile(board::BoardID::BODAQS_A8);
    const auto& rc3 = board::GetBoardProfile(board::BoardID::BODAQS_V1RC3);
    check(&a8 != &rc3 && std::strcmp(a8.name, rc3.name) != 0,
          "A8 and RC3 resolve to distinct named profiles");
    check(!a8.supports_user_sleep &&
              a8.buttons.binding_preset == board::ButtonBindingPreset::BodaqsA8,
          "A8 omits user sleep and selects its own button defaults");
    check(rc3.supports_user_sleep &&
              rc3.buttons.binding_preset == board::ButtonBindingPreset::BodaqsRc3,
          "RC3 retains user sleep and RC3 button defaults");
    check(board::GetBoardProfile(board::BoardID::ThingPlusS3_BODAQS_4_F).supports_user_sleep,
          "Prototype F retains user sleep");
    check(&board::GetBoardProfile(board::BoardID::BODAQS_S3_Mini_N4R2) == &a8 &&
              &board::GetBoardProfileByName("BODAQS S3 Mini N4R2") == &a8 &&
              &board::GetBoardProfileByName("BODAQS A8") == &a8 &&
              &board::GetBoardProfileByName("BODAQS V1RC3") == &rc3,
          "legacy Mini alias and explicit names select the intended profiles");

    std::printf("Board profiles: %d passed, %d failed\n", passed, failed);
    return failed;
}
