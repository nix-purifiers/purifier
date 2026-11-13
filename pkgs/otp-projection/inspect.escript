#!/usr/bin/env escript
%%! +S 2:2 +A 1 -noinput -no_dot_erlang
%% SPDX-License-Identifier: MIT
-mode(compile).

main(Args) ->
    try run(Args)
    catch Class:Reason:Stack ->
        io:format(standard_error, "purifier: compiled OTP: ~p:~p~n~p~n", [Class, Reason, Stack]),
        halt(1)
    end.

read_json(Path) -> {ok, Bytes} = file:read_file(Path), json:decode(Bytes).
text(Value) -> unicode:characters_to_binary(Value).
string(Value) -> unicode:characters_to_list(Value).
field(Key, Map) -> string(maps:get(Key, Map)).
check(true, _) -> ok;
check(false, Reason) -> error(Reason).
hash_file(Path) ->
    {ok, Bytes} = file:read_file(Path),
    string:lowercase(binary:encode_hex(crypto:hash(sha256, Bytes))).

facts() ->
    case application:load(compiler) of ok -> ok; {error, {already_loaded, compiler}} -> ok end,
    {ok, CompilerVersion} = application:get_key(compiler, vsn),
    #{otp => text(erlang:system_info(otp_release)), erts => text(erlang:system_info(version)),
      architecture => text(erlang:system_info(system_architecture)),
      nifVersion => text(erlang:system_info(nif_version)), runtimeRoot => text(code:root_dir()),
      compiler => text(code:which(compile)), compilerVersion => text(CompilerVersion),
      erlc => text(os:find_executable("erlc")),
      os => text(atom_to_list(element(2, os:type())))}.

app_props(Directory) ->
    Files = filelib:wildcard(filename:join([Directory, "ebin", "*.app"])),
    check(length(Files) =:= 1, {expected_one_native_application, Directory}),
    [File] = Files,
    {ok, [{application, App, Props}]} = file:consult(File),
    check(filename:basename(File) =:= atom_to_list(App) ++ ".app", app_filename_mismatch),
    {App, Props, File}.

application(Row, Runtime, Facts, Allowed) ->
    Directory = field(<<"directory">>, Row),
    {App, Props, File} = app_props(Directory),
    check(code:lib_dir(App) =:= {error, bad_name}, {runtime_application_collision, App}),
    ObservationFile = field(<<"observation">>, Row),
    {ok, [Observation]} = file:consult(ObservationFile),
    check(maps:get(format, Observation) =:= "purifier-otp-production-v1", unsupported_production_observation),
    check(maps:get(runtime, Observation) =:= Runtime, production_runtime_input_mismatch),
    lists:foreach(fun({Key, NativeKey}) ->
        check(text(maps:get(Key, Observation)) =:= maps:get(NativeKey, Facts), {production_runtime_mismatch, Key})
    end, [{otp, otp}, {erts, erts}, {architecture, architecture}, {nifVersion, nifVersion},
          {runtimeRoot, runtimeRoot}, {compilerPath, compiler}, {compilerVersion, compilerVersion}]),
    BeamFiles = lists:sort(filelib:wildcard(filename:join([Directory, "ebin", "*.beam"]))),
    Actual = [beam(B, Observation, Facts, Allowed) || B <- BeamFiles],
    Modules = [maps:get(name, B) || B <- Actual],
    Declared = [atom_to_binary(M) || M <- proplists:get_value(modules, Props, [])],
    check(length(Declared) =:= length(lists:usort(Declared)) andalso lists:sort(Declared) =:= lists:sort(Modules),
          {incomplete_application_modules, App}),
    check(lists:sort(maps:get(modules, Observation)) =:= lists:sort([binary_to_atom(M) || M <- Modules]),
          {production_modules_mismatch, App}),
    check(length(maps:get(compiled, Observation)) =:= length(Modules), {production_compiled_modules_mismatch, App}),
    Version = proplists:get_value(vsn, Props),
    check(is_list(Version) andalso Version =/= [], {invalid_native_application_version, App}),
    #{name => atom_to_binary(App), version => text(Version), sourceDirectory => text(Directory),
      observation => text(ObservationFile), origin => maps:get(<<"origin">>, Row),
      originIdentity => maps:get(<<"originIdentity">>, Row),
      originDirectory => maps:get(<<"originDirectory">>, Row), root => maps:get(<<"root">>, Row),
      compilerExecutable => text(maps:get(erlc, Observation)),
      appSHA256 => hash_file(File), modules => Actual,
      required => [atom_to_binary(A) || A <- proplists:get_value(applications, Props, [])],
      included => [atom_to_binary(A) || A <- proplists:get_value(included_applications, Props, [])],
      optional => [atom_to_binary(A) || A <- proplists:get_value(optional_applications, Props, [])]}.

beam(File, Observation, Facts, Allowed) ->
    {ok, {Mod, Chunks}} = beam_lib:chunks(File, [exports, imports, compile_info]),
    check(atom_to_list(Mod) =:= filename:basename(File, ".beam"), {beam_filename_mismatch, Mod}),
    check(code:which(Mod) =:= non_existing, {runtime_module_collision, Mod}),
    Matches = [B || B <- maps:get(compiled, Observation), maps:get(module, B) =:= Mod],
    [Recorded] = Matches,
    check(maps:get(chunks, Recorded) =:= Chunks, {production_beam_chunks_mismatch, Mod}),
    RecordedFile = maps:get(file, Recorded),
    check(filename:pathtype(RecordedFile) =:= absolute andalso
          not lists:any(fun(P) -> P =:= "." orelse P =:= ".." end, filename:split(RecordedFile)) andalso
          lists:any(fun(Root) -> lists:prefix(string(Root) ++ "/", RecordedFile) end, Allowed),
          {production_beam_outside_declared_closure, Mod}),
    check(hash_file(RecordedFile) =:= hash_file(File), {production_beam_bytes_mismatch, Mod}),
    CompileInfo = proplists:get_value(compile_info, Chunks),
    check(text(proplists:get_value(version, CompileInfo)) =:= maps:get(compilerVersion, Facts),
          {production_compiler_mismatch, Mod}),
    Imports = proplists:get_value(imports, Chunks),
    check(not lists:any(fun({M, F, _}) ->
        (M =:= erlang andalso F =:= load_nif) orelse M =:= erl_ddll
    end, Imports), {custom_native_loader_needs_separate_contract, Mod}),
    #{name => atom_to_binary(Mod), sha256 => hash_file(File), recordedFile => text(RecordedFile),
      imports => [#{module => atom_to_binary(M), function => atom_to_binary(F), arity => A} || {M,F,A} <- Imports]}.

deduplicate([], Acc) -> lists:reverse(Acc);
deduplicate([App | Rest], Acc) ->
    Same = [A || A <- Acc, maps:get(name, A) =:= maps:get(name, App)],
    case Same of
        [] -> deduplicate(Rest, [App | Acc]);
        [Prior] ->
            check(maps:get(originIdentity, Prior) =:= maps:get(originIdentity, App)
                  andalso maps:get(observation, Prior) =:= maps:get(observation, App)
                  andalso maps:get(appSHA256, Prior) =:= maps:get(appSHA256, App)
                  andalso maps:get(modules, Prior) =:= maps:get(modules, App), duplicate_application_owners),
            Merged = Prior#{root => maps:get(root, Prior) orelse maps:get(root, App)},
            deduplicate(Rest, [Merged | lists:delete(Prior, Acc)])
    end.

closure([], _, Seen) -> Seen;
closure([Name | Rest], Apps, Seen) ->
    case maps:is_key(Name, Seen) of
        true -> closure(Rest, Apps, Seen);
        false ->
            Entry = case maps:find(Name, Apps) of
                {ok, App} -> App;
                error -> runtime_app(Name)
            end,
            Required = (maps:get(required, Entry) -- maps:get(optional, Entry)) ++ maps:get(included, Entry),
            %% Optional apps that are present still participate in ownership/closure.
            Optional = maps:get(optional, Entry),
            check(lists:all(fun(N) -> lists:member(N, maps:get(required, Entry)) end, Optional),
                  {invalid_optional_application_metadata, Name}),
            PresentOptional = [N || N <- Optional, maps:is_key(N, Apps) orelse runtime_available(N)],
            closure(Rest ++ Required ++ PresentOptional, Apps, Seen#{Name => Entry})
    end.

runtime_available(Name) ->
    Directory = code:lib_dir(binary_to_atom(Name)),
    is_list(Directory) andalso lists:prefix(code:root_dir() ++ "/", Directory).

runtime_app(Name) ->
    Atom = binary_to_atom(Name),
    Directory = code:lib_dir(Atom),
    check(is_list(Directory) andalso lists:prefix(code:root_dir() ++ "/", Directory),
          {missing_required_compiled_application, Name}),
    {Atom, Props, File} = app_props(Directory),
    #{name => Name, version => text(proplists:get_value(vsn, Props)), sdk => true,
      directory => text(Directory), appSHA256 => hash_file(File),
      required => [atom_to_binary(A) || A <- proplists:get_value(applications, Props, [])],
      included => [atom_to_binary(A) || A <- proplists:get_value(included_applications, Props, [])],
      optional => [atom_to_binary(A) || A <- proplists:get_value(optional_applications, Props, [])]}.

run(["inspect", Input, Output]) ->
    Spec = read_json(Input), Facts = facts(),
    Allowed = read_json(field(<<"closure">>, Spec)),
    Rows = [application(R, field(<<"runtime">>, Spec), Facts, Allowed) || R <- maps:get(<<"applications">>, Spec)],
    Apps = deduplicate(Rows, []),
    Modules = lists:append([[maps:get(name, M) || M <- maps:get(modules, A)] || A <- Apps]),
    check(length(Modules) =:= length(lists:usort(Modules)), duplicate_compiled_module_owners),
    Roots = [maps:get(name, A) || A <- Apps, maps:get(root, A)],
    Closure = closure(Roots, maps:from_list([{maps:get(name, A), A} || A <- Apps]), #{}),
    Selected = [A || A <- Apps, maps:is_key(maps:get(name, A), Closure)],
    SDK = [A || A <- maps:values(Closure), maps:get(sdk, A, false)],
    Model = #{runtimeFacts => Facts, roots => Roots, applications => Selected, runtimeApplications => SDK},
    ok = file:write_file(Output, json:encode(Model));
run(["verify", CatalogFile, Out]) ->
    Catalog = read_json(CatalogFile),
    Apps = maps:get(<<"applications">>, Catalog),
    lists:foreach(fun(A) ->
        Directory = filename:join(Out, field(<<"directory">>, A)),
        true = code:add_patha(filename:join(Directory, "ebin"))
    end, Apps),
    lists:foreach(fun(A) ->
        App = binary_to_atom(maps:get(<<"name">>, A)),
        case application:load(App) of ok -> ok; {error, {already_loaded, App}} -> ok end,
        {ok, Version} = application:get_key(App, vsn),
        check(text(Version) =:= maps:get(<<"version">>, A), {loaded_app_version_mismatch, App}),
        lists:foreach(fun(M) ->
            Mod = binary_to_atom(maps:get(<<"name">>, M)),
            {module, Mod} = code:ensure_loaded(Mod),
            Expected = filename:join([Out, field(<<"directory">>, A), "ebin", atom_to_list(Mod) ++ ".beam"]),
            check(code:which(Mod) =:= Expected, {loaded_module_origin_mismatch, Mod})
        end, maps:get(<<"modules">>, A))
    end, Apps),
    lists:foreach(fun(Name) ->
        {ok, _} = application:ensure_all_started(binary_to_atom(Name))
    end, maps:get(<<"roots">>, Catalog)),
    io:format("compiled OTP: native application closure startup and module origins verified~n");
run(_) -> error(invalid_compiled_otp_invocation).
