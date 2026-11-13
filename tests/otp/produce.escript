#!/usr/bin/env escript
%%! +S 2:2 +A 1
-mode(compile).
main([Out, Runtime]) ->
    application:load(compiler),
    {ok, CompilerVersion} = application:get_key(compiler, vsn),
    Specs = [
        {otp_fixture_dep, "value() -> 40.", [kernel, stdlib], [], []},
        {otp_fixture_app, "value() -> otp_fixture_dep:value() + 2.", [kernel, stdlib, otp_fixture_dep], [], []},
        {otp_fixture_optional, "value() -> 42.", [kernel, stdlib, otp_fixture_dep, absent_optional, crypto], [], [otp_fixture_dep, absent_optional, crypto]},
        {otp_fixture_included, "value() -> otp_fixture_dep:value() + 2.", [kernel, stdlib], [otp_fixture_dep], []}
    ],
    lists:foreach(fun({Name, Body, Required, Included, Optional}) ->
        Directory = filename:join([Out, "lib", atom_to_list(Name)]),
        Ebin = filename:join(Directory, "ebin"),
        ok = filelib:ensure_dir(filename:join(Ebin, "placeholder")),
        Source = filename:join(Directory, atom_to_list(Name) ++ ".erl"),
        ok = file:write_file(Source, io_lib:format("-module(~p).~n-export([value/0]).~n~s~n", [Name, Body])),
        {ok, Name} = compile:file(Source, [{outdir, Ebin}, report_errors, report_warnings]),
        Beam = filename:join(Ebin, atom_to_list(Name) ++ ".beam"),
        {ok, {Name, Chunks}} = beam_lib:chunks(Beam, [exports, imports, compile_info]),
        Props = [{vsn, "1.2.3"}, {modules, [Name]}, {applications, Required},
                 {included_applications, Included}, {optional_applications, Optional}],
        ok = file:write_file(filename:join(Ebin, atom_to_list(Name) ++ ".app"),
                             io_lib:format("~p.~n", [{application, Name, Props}])),
        Observation = #{format => "purifier-otp-production-v1", runtime => Runtime,
            otp => erlang:system_info(otp_release), erts => erlang:system_info(version),
            architecture => erlang:system_info(system_architecture),
            nifVersion => erlang:system_info(nif_version), runtimeRoot => code:root_dir(),
            compilerPath => code:which(compile), compilerVersion => CompilerVersion,
            erlc => os:find_executable("erlc"), modules => [Name],
            compiled => [#{module => Name, file => Beam, chunks => Chunks}]},
        ok = file:write_file(filename:join(Ebin, "otp-observation.term"), io_lib:format("~p.~n", [Observation]))
    end, Specs),
    Header = filename:join([Out, "lib", "otp_fixture_dep", "include", "value.hrl"]),
    ok = filelib:ensure_dir(Header),
    ok = file:write_file(Header, "-define(OTP_VALUE, 42).\n"),
    ok = filelib:ensure_dir(filename:join([Out, "lib", "otp_fixture_dep", "priv", "empty", "placeholder"])).
